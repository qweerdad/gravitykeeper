"""Local project/workspace catalogue and bounded, Unicode transcript search."""

from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote

from .exporter import dump_json
from .storage import load_json, relative_name


CATALOG = "05_Project_Index/PROJECTS.json"


def label(text):
    return str(text).replace("|", "\\|").replace("[", "\\[").replace("]", "\\]").replace("\r", " ").replace("\n", " ")


def build_catalog(root, report):
    projects = defaultdict(list)
    for session in report["sessions"]:
        summary = session["summary"]
        key = (session["profile"], str(summary.get("project_id", "")), tuple(session["workspace_paths"]))
        projects[key].append({
            "title": summary.get("title") or "Untitled conversation",
            "uuid": summary["conversation_id"], "parent": summary.get("parent_conversation_id") or "",
            "status": session["status"], "markdown": session["markdown"], "json": session["json"],
            "last_activity": summary.get("last_modified_time") or "",
            "steps": sum(session["counts_by_type"].values()),
            "issues": session["verification"]["anomalies"],
        })
    groups = [{"profile": profile, "project_id": project, "workspace_paths": list(paths), "sessions": sessions}
              for (profile, project, paths), sessions in projects.items()]
    counts = dict(Counter(session["status"] for session in report["sessions"]))
    result = {"format": 1, "counts": counts, "projects": groups}
    dump_json(root / CATALOG, result)
    lines = ["# Project and workspace index", "", "Generated locally by GravityKeeper.", ""]
    for group in groups:
        path = ", ".join(group["workspace_paths"]) or "No workspace recorded"
        lines.extend([f"## {label(path)}", "",
                      "| Conversation | Parent UUID | Export status | JSON |",
                      "| --- | --- | --- | --- |"])
        for item in group["sessions"]:
            md = quote("../" + item["markdown"], safe="/")
            data = quote("../" + item["json"], safe="/")
            lines.append(f"| [{label(item['title'])}]({md}) | {item['parent']} | {item['status']} | [JSON]({data}) |")
        lines.append("")
    (root / "05_Project_Index" / "INDEX.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return result


def local_file(root, path):
    relative_name(path)
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root.resolve()) or not candidate.is_file():
        raise ValueError("Conversation file is missing or outside the selected snapshot")
    return candidate


def catalog(root):
    index = root / CATALOG
    if not index.is_file():
        return {"format": 1, "counts": {}, "projects": []}
    return load_json(index)


def sessions(root):
    for group in catalog(root)["projects"]:
        for item in group["sessions"]:
            yield item | {"workspace_paths": group["workspace_paths"], "profile": group["profile"]}


def transcript(root, item):
    return load_json(local_file(root, item["json"]))


def search(root, text, limit=200, progress=None):
    needle = text.strip().casefold()
    entries = list(sessions(root))
    hits = []
    if not needle:
        return [item | {"matches": 0, "snippet": ""} for item in entries]
    for position, item in enumerate(entries, 1):
        count = 0
        excerpt = ""
        for row in transcript(root, item)["steps"]:
            value = row.get("content") or row.get("error")
            if not isinstance(value, str):
                continue
            first = value.casefold().find(needle)
            if first >= 0:
                count += 1
                if not excerpt:
                    excerpt = " ".join(value[max(0, first - 30):first + 135].split())
        if count or any(needle in field.casefold() for field in [item["title"], item["uuid"], *item["workspace_paths"]]):
            hits.append(item | {"matches": count, "snippet": excerpt})
        if progress:
            progress("search", position, len(entries))
    return hits[:limit]
