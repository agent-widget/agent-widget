#!/usr/bin/env python3
"""agent-widget quality gate.

Checks (exit 1 on any failure, 0 on pass):
  1. Spelling: codespell if installed, else a built-in common-typo table.
  2. JSON/JSONL validity for all *.json / *.jsonl (excluding vendored dirs).
  3. Whitespace: trailing whitespace and missing trailing newline in text files.
  4. Required repository files exist.
Reports (INFO only, do not fail):
  5. Warning-term tokens (FT6336U / ST7796 / CST816 / GT911 / ILI9341 / TFT_eSPI)
     that must only appear as deliberate warnings, not as production config.

Usage: python3 scripts/check_quality.py [paths...]   (default: repo root)
Allowlist: scripts/typo_allowlist.txt (one word per line, '#' comments).
"""
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Directories that are never scanned (vendored, generated, or local-only).
EXCLUDE_DIRS = {
    ".git", "node_modules", "build", "bin", "dist", ".venv", "venv",
    "__pycache__", ".pio", ".idf", "managed_components", ".tmp",
    "lvgl",  # vendored LVGL under sim/lvgl-sim/lvgl
    # gitignored historical PoC material (not part of the tracked deliverable)
    "sim", "ota-verify", "wokwi-run",
    # gitignored local-only internal material (never pushed)
    "docs.local",
    # gitignored local toolchain (arduino-cli + esp32 core, ~1GB)
    "arduino-tool",
}
TEXT_EXTS = {".c", ".h", ".cpp", ".hpp", ".ino", ".md", ".json", ".jsonl",
             ".py", ".cmake", ".txt", ".yml", ".yaml", ".sh", ".csv", ".toml"}

REQUIRED_FILES = [
    "docs/architecture/00-repository-organization-design.md",
    "docs/hardware/board-spec-constraints.md",
    "docs.local/session/intake.md", "docs.local/session/plan.md",
    "docs.local/tasks.json", "docs.local/progress.jsonl",
    "docs.local/operations/code-quality-constraints.md",
    "scripts/check_quality.py",
]

WARN_TOKENS = ["FT6336U", "ST7796", "CST816", "GT911", "ILI9341", "TFT_eSPI"]

# Common typos in engineering text/code (word -> correction).
TYPOS = {
    "recieve": "receive", "recieved": "received", "seperate": "separate",
    "seperated": "separated", "occured": "occurred", "occurence": "occurrence",
    "adress": "address", "adresses": "addresses", "definately": "definitely",
    "teh": "the", "lenght": "length", "widht": "width", "heigth": "height",
    "hieght": "height", "retreive": "retrieve", "retreived": "retrieved",
    "sucess": "success", "sucessful": "successful", "sucessfully": "successfully",
    "faild": "failed", "fialed": "failed", "intialize": "initialize",
    "intialized": "initialized", "intialization": "initialization",
    "paramter": "parameter", "paramters": "parameters", "acces": "access",
    "allign": "align", "arround": "around", "availible": "available",
    "becuase": "because", "begining": "beginning", "calender": "calendar",
    "commited": "committed", "compatable": "compatible", "compatiblity": "compatibility",
    "configration": "configuration", "conifg": "config", "contianer": "container",
    "conrol": "control", "corrent": "current", "decription": "description",
    "depedency": "dependency", "devolop": "develop", "diffrent": "different",
    "enviroment": "environment", "exmaple": "example", "fucntion": "function",
    "gaurd": "guard", "implmentation": "implementation", "independant": "independent",
    "infomation": "information", "interupt": "interrupt", "messge": "message",
    "neccessary": "necessary", "ocurred": "occurred", "opration": "operation",
    "overide": "override", "perfrom": "perform", "proces": "process",
    "proccess": "process", "proeprty": "property", "protocal": "protocol",
    "reponse": "response", "responce": "response", "resorce": "resource",
    "sould": "should", "spefic": "specific", "syatem": "system",
    "temparature": "temperature", "thier": "their", "trasnfer": "transfer",
    "unkown": "unknown", "untill": "until", "vaule": "value", "verson": "version",
    "waht": "what", "wich": "which", "writeing": "writing", "aditional": "additional",
    "agian": "again", "alow": "allow", "analsis": "analysis", "arguement": "argument",
    "avaiable": "available", "bandwith": "bandwidth", "belive": "believe",
    "benifit": "benefit", "boundry": "boundary", "componant": "component",
    "conection": "connection", "consitent": "consistent", "corect": "correct",
    "dependcies": "dependencies", "depricated": "deprecated", "desciption": "description",
    "disconect": "disconnect", "dispay": "display", "effecient": "efficient",
    "existance": "existence", "excecute": "execute", "familliar": "familiar",
    "finial": "final", "forc": "force", "garantee": "guarantee",
    "gurantee": "guarantee", "imediately": "immediately", "importent": "important",
    "incomming": "incoming", "instace": "instance", "insted": "instead",
    "integar": "integer", "intreface": "interface", "invaid": "invalid",
    "knwon": "known", "legnth": "length", "libaray": "library",
    "managment": "management", "manfiest": "manifest", "mappin": "mapping",
    "memroy": "memory", "messsage": "message", "metod": "method",
    "mispell": "misspell", "missmatch": "mismatch", "moveing": "moving",
    "namepsace": "namespace", "neccesary": "necessary", "noticable": "noticeable",
    "nuber": "number", "numebr": "number", "obect": "object", "ocassion": "occasion",
    "occurance": "occurrence", "oject": "object", "optimze": "optimize",
    "orgin": "origin", "ouside": "outside", "peice": "piece",
    "performace": "performance", "persistant": "persistent", "possable": "possible",
    "postion": "position", "powerfull": "powerful", "preceed": "precede",
    "presist": "persist", "primative": "primitive", "probaly": "probably",
    "progess": "progress", "promiss": "promise", "publically": "publicly",
    "purpuse": "purpose", "quesion": "question", "quey": "query",
    "recomended": "recommended", "recrod": "record", "referece": "reference",
    "refrence": "reference", "relavent": "relevant", "remaing": "remaining",
    "remeber": "remember", "repersent": "represent", "reqest": "request",
    "requiered": "required", "requirment": "requirement", "reserach": "research",
    "reslove": "resolve", "resolut": "result", "resposibility": "responsibility",
    "retrun": "return", "rigth": "right", "rougly": "roughly", "runing": "running",
    "saftey": "safety", "sceen": "screen", "scedule": "schedule", "scirpt": "script",
    "seach": "search", "secound": "second", "sence": "sense", "serach": "search",
    "setuped": "set up", "shoud": "should", "similair": "similar", "similiar": "similar",
    "somthing": "something", "specifed": "specified", "stabel": "stable",
    "standart": "standard", "statment": "statement", "stoped": "stopped",
    "strees": "stress", "substract": "subtract", "supress": "suppress",
    "surce": "source", "symetric": "symmetric", "tabel": "table", "taks": "task",
    "temlate": "template", "templete": "template", "tesing": "testing",
    "thrid": "third", "tiem": "time", "tihs": "this", "timout": "timeout",
    "tme": "time", "ture": "true", "tyep": "type", "udpate": "update",
    "unavailible": "unavailable", "understnad": "understand", "unqiue": "unique",
    "unsuccesful": "unsuccessful", "updata": "update", "uplaod": "upload",
    "usally": "usually", "useing": "using", "usefull": "useful", "vaild": "valid",
    "vairous": "various", "varable": "variable", "varys": "varies", "vefify": "verify",
    "verfication": "verification", "versin": "version", "vlaue": "value",
    "wehn": "when", "whcih": "which", "whent": "when", "whihc": "which",
    "whta": "what", "widht": "width", "wierd": "weird", "wihch": "which",
    "wokr": "work", "writen": "written", "wrok": "work", "yera": "year",
    "defaut": "default", "deault": "default", "defualt": "default",
    "retun": "return", "retuns": "returns", "funktion": "function",
    "exeption": "exception", "atribute": "attribute",
    "atributes": "attributes", "dependend": "dependent", "dependancies": "dependencies",
}


def iter_text_files(paths):
    for base in paths:
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            if any(p in EXCLUDE_DIRS for p in dirpath.split(os.sep)):
                continue
            for fn in filenames:
                ext = os.path.splitext(fn)[1].lower()
                if ext in TEXT_EXTS:
                    yield os.path.join(dirpath, fn)


def load_allowlist():
    allow = set()
    p = os.path.join(ROOT, "scripts", "typo_allowlist.txt")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                w = line.strip()
                if w and not w.startswith("#"):
                    allow.add(w.lower())
    return allow


def split_words(text):
    """Extract ASCII word tokens, splitting camelCase/snake_case on boundaries."""
    words = set()
    for token in re.findall(r"[A-Za-z][A-Za-z0-9']*", text):
        if "'" in token:
            token = token.split("'")[0]
        words.add(token)
        # split camelCase / snake_case parts
        for part in re.split(r"[_\-]+", token):
            for sub in re.split(r"(?<=[a-z0-9])(?=[A-Z])", part):
                words.add(sub)
    return words


SELF = os.path.join("scripts", "check_quality.py")


def check_spelling(paths, allowlist):
    errors = []
    # Prefer codespell when available (much stronger dictionary).
    codespell = shutil.which("codespell")
    if codespell:
        skip_dirs = ",".join(EXCLUDE_DIRS)
        files = [p for p in iter_text_files(paths)]
        if not files:
            return errors
        ignore_file = os.path.join(ROOT, "scripts", "typo_allowlist.txt")
        cmd = [codespell, "-q", "3", "--skip=" + skip_dirs, "-L", ",".join(allowlist or [""])]
        if os.path.exists(ignore_file):
            cmd = [codespell, "-q", "3", "--skip=" + skip_dirs,
                   "--ignore-words=" + ignore_file]
        proc = subprocess.run(cmd + files, capture_output=True, text=True)
        if proc.returncode != 0:
            for line in proc.stdout.splitlines():
                errors.append(("spell", line.strip()))
        return errors
    # Built-in fallback.
    for path in iter_text_files(paths):
        if os.path.relpath(path, ROOT) == SELF:
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for lineno, line in enumerate(f, 1):
                    for w in split_words(line):
                        lw = w.lower()
                        if lw in allowlist:
                            continue
                        if lw in TYPOS:
                            errors.append(("spell", "%s:%d: '%s' -> '%s'" % (
                                os.path.relpath(path, ROOT), lineno, w, TYPOS[lw])))
        except OSError:
            pass
    return errors


def check_json(paths):
    errors = []
    for path in iter_text_files(paths):
        ext = os.path.splitext(path)[1].lower()
        if ext not in (".json", ".jsonl"):
            continue
        rel = os.path.relpath(path, ROOT)
        try:
            if ext == ".json":
                with open(path, encoding="utf-8") as f:
                    json.load(f)
            else:
                with open(path, encoding="utf-8") as f:
                    for lineno, line in enumerate(f, 1):
                        line = line.strip()
                        if line:
                            try:
                                json.loads(line)
                            except json.JSONDecodeError as e:
                                errors.append(("json", "%s:%d: %s" % (rel, lineno, e)))
        except json.JSONDecodeError as e:
            errors.append(("json", "%s: %s" % (rel, e)))
        except OSError:
            pass
    return errors


def check_whitespace(paths):
    errors = []
    for path in iter_text_files(paths):
        if os.path.relpath(path, ROOT) == SELF:
            continue
        rel = os.path.relpath(path, ROOT)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                data = f.read()
        except OSError:
            continue
        for lineno, line in enumerate(data.split("\n"), 1):
            if line.rstrip(" \t") != line:
                errors.append(("ws", "%s:%d: trailing whitespace" % (rel, lineno)))
                break
        if data and not data.endswith("\n"):
            errors.append(("ws", "%s: missing trailing newline" % rel))
    return errors


def check_required():
    missing = []
    for f in REQUIRED_FILES:
        if not os.path.exists(os.path.join(ROOT, f)):
            missing.append(f)
    return [("required", "missing file: " + f) for f in missing]


def report_tokens(paths):
    for path in iter_text_files(paths):
        if os.path.relpath(path, ROOT) == SELF:
            continue
        ext = os.path.splitext(path)[1].lower()
        if ext not in TEXT_EXTS:
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for lineno, line in enumerate(f, 1):
                    for tok in WARN_TOKENS:
                        if tok in line:
                            print("INFO term %s:%d: %s" % (
                                os.path.relpath(path, ROOT), lineno, tok))
        except OSError:
            pass


def main():
    paths = sys.argv[1:] or [ROOT]
    allowlist = load_allowlist()
    errors = []
    errors += check_spelling(paths, allowlist)
    errors += check_json(paths)
    errors += check_whitespace(paths)
    errors += check_required()
    report_tokens(paths)

    if errors:
        print("FAIL %d issue(s):" % len(errors))
        for kind, msg in errors:
            print("  [%s] %s" % (kind, msg))
        return 1
    print("PASS: spelling / JSON / whitespace / required-files checks clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
