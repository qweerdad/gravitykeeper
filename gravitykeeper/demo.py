"""Generate a deterministic fictional profile for demos and packaging smoke tests."""

from base64 import b64decode
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from urllib.parse import quote


CONVERSATIONS = (
    ("10000000-0000-4000-8000-000000000001", "Station accessibility review", "Transit Studio", "",
     "Review the fictional Riverside Station for step-free connections and propose a concise inspection checklist.",
     "The fictional station has two transfer paths. Review ramp landing clearance, platform signs, and help-point placement."),
    ("10000000-0000-4000-8000-000000000002", "Evening service field notes", "Transit Studio", "10000000-0000-4000-8000-000000000001",
     "Summarize the practice observer notes from the fictional night service.",
     "The demo notes suggest adjusting sign contrast and simplifying the platform transfer map."),
    ("10000000-0000-4000-8000-000000000003", "Exhibit lighting prototype", "Museum Workshop", "",
     "Compare two fictional display lighting layouts for a small exhibit.",
     "Layout B has fewer shadows across the sample labels. Record brightness and glare as separate observations."),
    ("10000000-0000-4000-8000-000000000004", "展览导览词草稿", "Museum Workshop", "",
     "请为虚构的城市博物馆写一段简短的展览导览词。",
     "欢迎来到城市展览。请沿地面指引前行，留意每件展品旁的故事卡片。"),
)


def varint(number):
    data = bytearray()
    while number > 127:
        data.append((number & 127) | 128)
        number >>= 7
    return bytes(data) + bytes([number])


def field(number, data):
    return varint(number * 8 + 2) + varint(len(data)) + data


def fixture(root, rows_per_session=0):
    root.mkdir(parents=True, exist_ok=False)
    raw_db = root / "conversations"
    raw_db.mkdir()
    date = "2026-01-15T10:00:00Z"
    with closing(sqlite3.connect(root / "conversation_summaries.db")) as index:
        index.execute("""CREATE TABLE conversation_summaries(
            conversation_id TEXT, title TEXT, last_modified_time TEXT, workspace_uris TEXT,
            step_count INT, project_id TEXT, parent_conversation_id TEXT, raw_summary BLOB)""")
        for i, (uid, title, group, parent, prompt, reply) in enumerate(CONVERSATIONS):
            logs = root / "brain" / uid / ".system_generated" / "logs"
            chunks = logs / "chunks" / "transcript_full"
            chunks.mkdir(parents=True)
            rows = [
                {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
                 "created_at": date, "content": f"<USER_REQUEST>\n{prompt}\n</USER_REQUEST>"},
                {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
                 "created_at": date, "content": reply},
            ]
            if rows_per_session and i == 0:
                for j in range(2, rows_per_session):
                    rows.append({"step_index": j, "source": "MODEL", "type": "GENERIC", "status": "DONE",
                                 "created_at": date, "content": f"Synthetic progress fragment {j:06d}. " + "Sample line. " * 20})
            if i == 0:
                media = logs / "media"
                media.mkdir()
                sample_png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a8r8AAAAASUVORK5CYII="
                (media / "synthetic-marker.png").write_bytes(b64decode(sample_png))
                rows[1]["media"] = [{"mime_type": "image/png",
                                     "uri": f"file:///C:/FictionalProfile/brain/{uid}/.system_generated/logs/media/synthetic-marker.png"}]
            payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode("utf-8")
            (logs / "transcript_full.jsonl").write_bytes(payload)
            (chunks / "00000000.jsonl").write_bytes(payload[:len(payload) // 2])
            (chunks / "00000001.jsonl").write_bytes(payload[len(payload) // 2:])
            (logs / "transcript.jsonl").write_bytes(payload)
            with closing(sqlite3.connect(raw_db / (uid + ".db"))) as db:
                db.execute("CREATE TABLE steps(idx INTEGER PRIMARY KEY, step_type INT, step_payload BLOB)")
                db.execute("INSERT INTO steps VALUES (0,14,?)", (field(19, field(2, prompt.encode())),))
                db.execute("INSERT INTO steps VALUES (1,15,?)", (field(20, reply.encode()),))
                db.executemany("INSERT INTO steps VALUES (?,132,?)",
                               ((j, b"") for j in range(2, len(rows))))
                db.commit()
            index.execute("INSERT INTO conversation_summaries VALUES (?,?,?,?,?,?,?,NULL)",
                          (uid, title, date, json.dumps(["file:///C:/DemoWorkspaces/" + quote(group)]),
                           len(rows), group.lower(), parent))
        index.commit()
    brain = root / "brain" / CONVERSATIONS[0][0]
    (brain / "implementation_plan.md").write_text("# Fictional inspection plan\n\n1. Inspect navigation signs.\n", encoding="utf-8")
    (brain / "walkthrough.md").write_text("# Fictional walkthrough\n\nDemo inspection complete.\n", encoding="utf-8")
    task = brain / ".system_generated" / "tasks"
    task.mkdir()
    (task / "001.log").write_text("Fictional task complete\n", encoding="utf-8")
    return root
