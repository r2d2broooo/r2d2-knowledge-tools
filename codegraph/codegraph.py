"""Code graph — a local, deterministic symbol map of our own Python codebase.

Minimal self-hosted take on Graphify (github.com/Graphify-Labs/graphify): build a queryable graph of
modules / functions / classes / methods and the edges between them (DEFINES, IMPORTS, CALLS), so
navigation is "trace the graph" instead of grepping — and every call edge is tagged EXTRACTED (same
module, or an imported name) vs INFERRED (name-resolved across modules without an import link, so
treat as a lead, not a fact). No dependencies: Python's stdlib `ast` replaces Graphify's tree-sitter
(our code is Python, so this is cleaner than a 36-language parser). Supports [[operating_standard]]'s
"grep/open before citing a symbol" — query this first to find where something really lives.

CLI:
  python -m shared.codegraph build                 # (re)build data/codegraph.json
  python -m shared.codegraph find NAME             # where a symbol is defined (file:line)
  python -m shared.codegraph callers NAME          # what calls NAME
  python -m shared.codegraph callees NAME          # what NAME calls (our own funcs)
  python -m shared.codegraph explain NAME          # definition + imports + callers + callees
  python -m shared.codegraph path A B              # shortest connection between two symbols
"""
import ast
import json
import os
import time
from collections import deque

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # telegram-bots/
STORE = os.path.join(ROOT, "data", "codegraph.json")
_SKIP_DIRS = {"venv", ".venv", "node_modules", ".git", "__pycache__", "backups", "cloud-workdir",
              "claude-workdir", ".mypy_cache", ".pytest_cache"}
_MAX_CALL_CANDIDATES = 12   # a call name matching more defs than this is too ambiguous to link
# Container/stdlib/dataframe method names: a `.get()`/`.items()` call is dict/df method access, NOT a
# call to one of our functions that happens to share the name — never resolve these (kills hub noise).
_STOP_NAMES = {
    "get", "set", "pop", "append", "extend", "insert", "remove", "update", "keys", "values", "items",
    "add", "discard", "clear", "copy", "setdefault", "format", "join", "split", "strip", "lstrip",
    "rstrip", "replace", "lower", "upper", "startswith", "endswith", "encode", "decode", "read",
    "write", "close", "flush", "sort", "reverse", "to_numpy", "mean", "std", "sum", "min", "max",
    "astype", "reshape", "fillna", "dropna", "apply", "raise_for_status", "dumps", "loads",
}


def _module_id(path: str, root: str) -> str:
    rel = os.path.relpath(path, root)[:-3]                 # strip .py
    if rel.endswith(os.sep + "__init__"):
        rel = rel[: -len(os.sep + "__init__")]
    return rel.replace(os.sep, ".")


def _callee_name(call: ast.Call):
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _resolve_import(module_id, node):
    """Yield internal module ids an import statement refers to (best-effort), plus imported names."""
    mods, names = [], []
    if isinstance(node, ast.Import):
        for a in node.names:
            mods.append(a.name)
            names.append((a.asname or a.name).split(".")[0])
    elif isinstance(node, ast.ImportFrom):
        base = module_id.split(".")
        if node.level:                                    # relative import
            base = base[: len(base) - node.level] if node.level <= len(base) else []
            pkg = ".".join(base)
            root_mod = f"{pkg}.{node.module}" if node.module else pkg
        else:
            root_mod = node.module or ""
        for a in node.names:
            names.append(a.asname or a.name)
            mods.append(f"{root_mod}.{a.name}" if root_mod else a.name)   # from X import Y -> X.Y (module?)
        if root_mod:
            mods.append(root_mod)                          # ... or Y is a name from module X
    return mods, names


def build(root: str = ROOT) -> dict:
    nodes: dict = {}
    defines, imports_edges = [], []
    calls_raw = []                                         # (caller_id, callee_name)
    imports_map: dict = {}                                 # module_id -> {"mods": set, "names": set}
    name_index: dict = {}                                  # simple name -> [node ids]
    n_files = n_err = 0

    py_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")
                       and not d.startswith("venv") and d not in ("site-packages", "dist-packages")]
        for fn in filenames:
            if fn.endswith(".py"):
                py_files.append(os.path.join(dirpath, fn))

    for path in py_files:
        mod = _module_id(path, root)
        try:
            tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
        except Exception:
            n_err += 1
            continue
        n_files += 1
        nodes[mod] = {"kind": "module", "name": mod.split(".")[-1], "module": mod,
                      "file": os.path.relpath(path, root), "line": 1}
        imports_map[mod] = {"mods": set(), "names": set()}

        def register(nid, kind, name, line):
            nodes[nid] = {"kind": kind, "name": name, "module": mod,
                          "file": os.path.relpath(path, root), "line": line}
            name_index.setdefault(name, []).append(nid)

        def walk(node, ctx_id, class_name):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    cid = f"{mod}:{child.name}"
                    register(cid, "class", child.name, child.lineno)
                    defines.append((mod, cid))
                    walk(child, cid, child.name)
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if class_name:
                        fid = f"{mod}:{class_name}.{child.name}"; parent = f"{mod}:{class_name}"; kind = "method"
                    else:
                        fid = f"{mod}:{child.name}"; parent = mod; kind = "function"
                    register(fid, kind, child.name, child.lineno)
                    defines.append((parent, fid))
                    walk(child, fid, None)
                elif isinstance(child, (ast.Import, ast.ImportFrom)):
                    m, nm = _resolve_import(mod, child)
                    imports_map[mod]["mods"].update(m)
                    imports_map[mod]["names"].update(nm)
                    walk(child, ctx_id, class_name)
                elif isinstance(child, ast.Call):
                    name = _callee_name(child)
                    if name:
                        calls_raw.append((ctx_id, name))
                    walk(child, ctx_id, class_name)
                else:
                    walk(child, ctx_id, class_name)

        walk(tree, mod, None)

    # ---- resolve edges ---------------------------------------------------------------------------
    edges = []
    for parent, child in defines:
        edges.append({"src": parent, "dst": child, "kind": "DEFINES", "evidence": "EXTRACTED"})
    # IMPORTS: link a module to any INTERNAL module it imports
    for mod, imp in imports_map.items():
        for target in imp["mods"]:
            if target in nodes and target != mod:
                edges.append({"src": mod, "dst": target, "kind": "IMPORTS", "evidence": "EXTRACTED"})
    # CALLS: resolve callee name to our own defs
    seen = set()
    for caller_id, name in calls_raw:
        if name in _STOP_NAMES:
            continue
        cands = [nid for nid in name_index.get(name, []) if nodes[nid]["kind"] in ("function", "method")]
        if not cands or len(cands) > _MAX_CALL_CANDIDATES:
            continue
        caller_mod = nodes.get(caller_id, {}).get("module", caller_id.split(":")[0])
        # A bare call to a name defined in the caller's OWN module resolves to that local def (Python
        # scoping) — so drop same-name defs from other modules instead of listing them all as INFERRED.
        same_mod = [nid for nid in cands if nodes[nid]["module"] == caller_mod]
        if same_mod:
            cands = same_mod
        ambiguous = len(cands) > 1
        for dst in cands:
            if dst == caller_id:
                continue
            key = (caller_id, dst)
            if key in seen:
                continue
            seen.add(key)
            dst_mod = nodes[dst]["module"]
            if ambiguous:
                ev = "INFERRED"
            elif dst_mod == caller_mod:
                ev = "EXTRACTED"
            elif dst_mod in imports_map.get(caller_mod, {}).get("mods", ()) \
                    or name in imports_map.get(caller_mod, {}).get("names", ()):
                ev = "EXTRACTED"
            else:
                ev = "INFERRED"
            edges.append({"src": caller_id, "dst": dst, "kind": "CALLS", "evidence": ev})

    graph = {"built_ts": time.time(), "root": root, "n_files": n_files, "parse_errors": n_err,
             "nodes": nodes, "edges": edges, "name_index": name_index}
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    json.dump(graph, open(STORE, "w"), default=str)
    return graph


# ------------------------------------------------------------------ query
def _load() -> dict:
    return json.loads(open(STORE).read())


def _match(g, name):
    """Node ids matching `name` — exact simple-name, else id substring."""
    idx = g["name_index"]
    if name in idx:
        return idx[name]
    hits = [nid for nid in g["nodes"] if name.lower() in nid.lower()]
    return hits


def _fmt(g, nid):
    n = g["nodes"].get(nid, {})
    return f"{nid}  [{n.get('kind')}]  {n.get('file')}:{n.get('line')}"


def find(name):
    g = _load()
    hits = _match(g, name)
    return [_fmt(g, nid) for nid in hits]


def callers(name):
    g = _load()
    targets = set(_match(g, name))
    out = [e["src"] for e in g["edges"] if e["kind"] == "CALLS" and e["dst"] in targets]
    return sorted(set(out))


def callees(name):
    g = _load()
    srcs = set(_match(g, name))
    out = [(e["dst"], e["evidence"]) for e in g["edges"] if e["kind"] == "CALLS" and e["src"] in srcs]
    return sorted(set(out))


def explain(name):
    g = _load()
    hits = _match(g, name)
    lines = []
    for nid in hits[:6]:
        lines.append(_fmt(g, nid))
        n = g["nodes"][nid]
        if n["kind"] == "module":
            imp = sorted({e["dst"] for e in g["edges"] if e["kind"] == "IMPORTS" and e["src"] == nid})
            if imp:
                lines.append("   imports: " + ", ".join(imp))
    cs = callers(name)
    ce = callees(name)
    if cs:
        lines.append("   called by: " + ", ".join(cs[:20]) + (" …" if len(cs) > 20 else ""))
    if ce:
        lines.append("   calls: " + ", ".join(f"{d}[{ev[0]}]" for d, ev in ce[:20]) + (" …" if len(ce) > 20 else ""))
    return lines


def path(a, b):
    g = _load()
    starts, goals = _match(g, a), set(_match(g, b))
    if not starts or not goals:
        return None
    adj: dict = {}
    for e in g["edges"]:
        adj.setdefault(e["src"], []).append((e["dst"], e["kind"]))
        adj.setdefault(e["dst"], []).append((e["src"], e["kind"]))     # undirected: "what connects"
    for start in starts:
        prev = {start: None}
        q = deque([start])
        while q:
            cur = q.popleft()
            if cur in goals:
                chain = []
                while cur is not None:
                    chain.append(cur)
                    cur = prev[cur]
                return list(reversed(chain))
            for nxt, _k in adj.get(cur, []):
                if nxt not in prev:
                    prev[nxt] = cur
                    q.append(nxt)
    return None


# ------------------------------------------------------------------ CLI
if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    arg2 = sys.argv[3] if len(sys.argv) > 3 else None
    if cmd == "build":
        g = build()
        print(f"built {STORE}: {g['n_files']} files, {len(g['nodes'])} nodes, {len(g['edges'])} edges "
              f"({g['parse_errors']} parse errors)")
    elif cmd == "find":
        print("\n".join(find(arg)) or "(no match)")
    elif cmd == "callers":
        print("\n".join(callers(arg)) or "(no callers found)")
    elif cmd == "callees":
        print("\n".join(f"{d}  [{ev}]" for d, ev in callees(arg)) or "(no callees found)")
    elif cmd == "explain":
        print("\n".join(explain(arg)) or "(no match)")
    elif cmd == "path":
        p = path(arg, arg2)
        print(" → ".join(p) if p else "(no path found)")
    else:
        print("usage: python -m shared.codegraph build|find|callers|callees|explain|path A [B]")
