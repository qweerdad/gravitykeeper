"""Export the copied Antigravity 2.33 session store using only the standard library."""

import base64
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
from tempfile import SpooledTemporaryFile
from urllib.parse import quote, unquote, urlsplit

from .capture import is_uuid
from .wire import descend, fields


STEP_TYPES = {14: "USER_INPUT", 15: "PLANNER_RESPONSE", 17: "ERROR_MESSAGE",
              23: "CHECKPOINT", 101: "SYSTEM_MESSAGE", 132: "GENERIC"}


def connect(path):
    if any(Path(str(path) + ext).exists() for ext in ("-wal", "-journal")):
        raw = next(parent for parent in path.parents if parent.name == "01_Raw_Backup")
        path = raw / "SQLite_Standalone" / path.relative_to(raw)
        if not path.is_file():
            raise ValueError(f"Missing verified standalone SQLite view: {path}")
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    return closing(connection)


def dump_json(path, value):
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def read_rows(path):
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def relative_link(from_dir, dest):
    return quote(Path(os.path.relpath(dest, from_dir)).as_posix(), safe="/")


def file_uri(uri):
    parts = urlsplit(uri)
    if parts.scheme != "file":
        return uri
    location = unquote(parts.path)
    if parts.netloc and parts.netloc != "localhost":
        return "\\\\" + parts.netloc + location.replace("/", "\\")
    return re.sub(r"^/(?=[a-zA-Z]:)", "", location).replace("/", "\\")


def fenced(text, language="text"):
    longest = max((len(run.group()) for run in re.finditer(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{text}\n{fence}\n\n"


def data_block(value):
    return fenced(json.dumps(value, ensure_ascii=False, indent=2), "json")


def text_or_json(value):
    return fenced(value) if isinstance(value, str) else data_block(value)


def recovered_error(row):
    """Validate and decode the wire layout against known type-17 log entries."""
    if row["step_format"] != 0 or row["status"] != 3:
        raise ValueError("unrecognized type-17 SQLite representation")
    payload, metadata = row["step_payload"], row["metadata"]
    message = descend(payload, 24, 3, 2).decode("utf-8")
    stamp = fields(descend(metadata, 1))
    timestamp = datetime.fromtimestamp(stamp[1][0], timezone.utc)
    raw = {key: base64.b64encode(row[key]).decode("ascii") for key in row.keys()
           if isinstance(row[key], bytes)}
    raw_info = {key: row[key] for key in row.keys() if not isinstance(row[key], bytes)}
    raw_info["blobs_base64"] = raw
    result = {"step_index": row["idx"], "source": "SYSTEM", "type": "ERROR_MESSAGE", "status": "DONE",
              "created_at": timestamp.isoformat(timespec="seconds").replace("+00:00", "Z"),
              "error": message, "recovered_from": "SQLite steps, protobuf field 24.3.2",
              "sqlite_step": raw_info}
    if 1 in fields(descend(payload, 24, 3)):
        result["content"] = "Error: " + message
    return result


def check_wire_against_logs(raw):
    checked = 0
    for source in (raw / "brain").glob("*/.system_generated/logs/transcript_full.jsonl"):
        known = {row["step_index"]: row for row in read_resilient(source)[0] if row["type"] == "ERROR_MESSAGE"}
        database = raw / "conversations" / (source.parents[2].name + ".db")
        if not known or not database.is_file():
            continue
        with connect(database) as db:
            for index, expected in known.items():
                row = db.execute("SELECT * FROM steps WHERE idx=? AND step_type=17", (index,)).fetchone()
                if row is None:
                    continue
                try:
                    actual = recovered_error(row)
                except (KeyError, ValueError, TypeError, IndexError):
                    return 0
                for key in ("step_index", "source", "type", "status", "created_at", "error", "content"):
                    if expected.get(key) != actual.get(key):
                        return 0
                checked += 1
    return checked


def read_stream(stream):
    rows = []
    invalid = 0
    for line in stream:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if (not isinstance(row, dict) or type(row.get("step_index")) is not int
                    or row["step_index"] < 0 or any(not isinstance(row.get(k), str)
                                                  for k in ("type", "source", "status"))):
                raise ValueError("invalid transcript envelope")
            rows.append(row)
        except (ValueError, UnicodeError):
            invalid += 1
    return rows, invalid


def read_resilient(path):
    if not path.is_file():
        return [], 0
    with path.open("rb") as stream:
        return read_stream(stream)


def rows_from_chunks(chunks, scratch):
    with SpooledTemporaryFile(max_size=8 * 1024 * 1024, dir=scratch) as assembled:
        for chunk in chunks:
            with chunk.open("rb") as source:
                shutil.copyfileobj(source, assembled)
        assembled.seek(0)
        return read_stream(assembled)


def expected_for_uuid(raw, uid, controls, blocked_db=False):
    source = raw / "brain" / uid / ".system_generated" / "logs" / "transcript_full.jsonl"
    thin_source = source.with_name("transcript.jsonl")
    if source.exists():
        input_path = source
    else:
        input_path = thin_source
    rows, invalid = read_resilient(input_path)
    db_path = raw / "conversations" / (uid + ".db")
    source_indices = [row["step_index"] for row in rows]
    errors = []
    recovered = []
    body_checks = Counter()
    if input_path != source:
        errors.append("full_transcript_missing")
    if invalid:
        errors.append(f"invalid_jsonl_lines:{invalid}")
    if any(row.get("truncated_fields") for row in rows):
        errors.append("truncated_transcript_fields")
    if source_indices != sorted(set(source_indices)):
        errors.append("duplicate_or_out_of_order_steps")
    chunks = sorted((source.parent / "chunks" / "transcript_full").glob("*.jsonl"))
    chunk_digest = hashlib.sha256()
    for chunk in chunks:
        with chunk.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                chunk_digest.update(block)
    chunks_match = bool(chunks) and source.exists() and chunk_digest.hexdigest() == digest(source)
    if not chunks_match:
        errors.append("transcript_chunks_unconfirmed")
    known = {}
    for row in rows:
        known.setdefault(row["step_index"], row)
    from_chunks = []
    if chunks and not chunks_match:
        candidates, invalid_chunks = rows_from_chunks(chunks, raw.parent.parent)
        if invalid_chunks:
            errors.append(f"invalid_chunk_lines:{invalid_chunks}")
        for row in candidates:
            index = row["step_index"]
            if index not in known or input_path != source:
                known[index] = row
                from_chunks.append(index)
    supplemental = []
    if input_path == source and thin_source.exists() and not chunks_match:
        for row in read_resilient(thin_source)[0]:
            if row["step_index"] not in known:
                known[row["step_index"]] = row
                supplemental.append(row["step_index"])
    rows = list(known.values())
    sql_steps = []
    if db_path.exists() and not blocked_db:
        try:
            with connect(db_path) as db:
                sql_steps = reconcile_sql(db, known, rows, errors, body_checks, recovered, controls)
        except (sqlite3.Error, ValueError, OSError, StopIteration):
            errors.append("corrupt_or_unsupported_database")
    else:
        errors.append("corrupt_or_unsupported_database" if blocked_db else "conversation_database_missing")
    rows.sort(key=lambda value: value["step_index"])
    if [row["step_index"] for row in rows] != [index for index, _ in sql_steps]:
        errors.append("step_coverage_mismatch")
    missing = sorted({index for index, _ in sql_steps} - {row["step_index"] for row in rows})
    return rows, {"transcript_rows": len(source_indices), "sqlite_steps": len(sql_steps),
                  "chunk_sha256_match": chunks_match, "recovered_sqlite_steps": recovered,
                  "supplemental_chunk_steps": from_chunks, "supplemental_compact_steps": supplemental,
                  "missing_step_indices": missing,
                  "text_matched_in_sqlite": dict(body_checks), "anomalies": errors}, input_path, db_path


def reconcile_sql(db, known, rows, errors, body_checks, recovered, controls):
            sql_steps = [(row["idx"], row["step_type"]) for row in db.execute(
                "SELECT idx, step_type FROM steps ORDER BY idx")]
            for index, kind in sql_steps:
                if index in known:
                    original = known[index]
                    if kind in STEP_TYPES and original["type"] != STEP_TYPES[kind]:
                        errors.append(f"step_type_mismatch:{index}")
                    if kind in (14, 15) and original.get("content"):
                        payload = db.execute("SELECT step_payload FROM steps WHERE idx=?", (index,)).fetchone()[0]
                        content = original["content"]
                        try:
                            if kind == 14:
                                prompt = descend(payload, 19, 2).decode("utf-8")
                                matched = content.startswith(f"<USER_REQUEST>\n{prompt}\n</USER_REQUEST>")
                            else:
                                matched = content.encode("utf-8") in payload
                        except (KeyError, ValueError, TypeError, IndexError):
                            matched = False
                        if matched:
                            body_checks[STEP_TYPES[kind]] += 1
                        else:
                            errors.append(f"step_content_mismatch:{index}")
                elif kind == 17 and controls:
                    try:
                        row = db.execute("SELECT * FROM steps WHERE idx=?", (index,)).fetchone()
                        rows.append(recovered_error(row))
                        recovered.append(index)
                    except (KeyError, ValueError, TypeError, IndexError):
                        errors.append(f"unsupported_error_message:{index}")
            return sql_steps


def tool_actions(rows):
    actions = []
    for row in rows:
        for call in row.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            name = call.get("name")
            if name not in {"write_file", "edit_file"}:
                continue
            args = call.get("args")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    continue
            if isinstance(args, dict) and args.get("Path"):
                actions.append({"tool_call_step_index": row["step_index"], "tool": name,
                                "reported_path": args["Path"]})
    return actions


def copy_artifacts(raw, target, archive, progress=None):
    grouped = defaultdict(list)
    sources = sorted(p for p in (raw / "brain").rglob("*") if p.is_file())
    for position, source in enumerate(sources, 1):
        rel = source.relative_to(raw / "brain")
        if progress:
            progress("artifacts", position, len(sources))
        if (rel.parts[1:3] == (".system_generated", "logs") and
                rel.parts[3] != "media"):
            continue
        output = target / rel
        output.parent.mkdir(exist_ok=True, parents=True)
        shutil.copy2(source, output)
        if digest(source) != digest(output):
            raise ValueError(f"brain artifact hash mismatch: {rel}")
        parts = rel.parts
        step = int(parts[3]) if parts[1:3] == (".system_generated", "steps") and parts[3].isdecimal() else None
        grouped[parts[0]].append({"path_within_archive": output.relative_to(archive).as_posix(),
                                  "step_index": step, "bytes": output.stat().st_size})
    return grouped


def media_index(rows, root, profile):
    index = defaultdict(list)
    for row in rows:
        for medium in row.get("media") or []:
            if not isinstance(medium, dict) or not isinstance(medium.get("uri"), str):
                index[row["step_index"]].append({"source_uri": None, "path_within_archive": None})
                continue
            uri = medium["uri"]
            try:
                parts = unquote(urlsplit(uri).path).replace("\\", "/").split("/")
            except ValueError:
                parts = []
            brain_indices = [index for index, part in enumerate(parts) if part.lower() == "brain"]
            rel = parts[brain_indices[-1] + 1:] if brain_indices else []
            local = None
            if rel and all(part not in {"", ".", ".."} and ":" not in part for part in rel):
                relative = Path("04_Brain_Artifacts", profile).joinpath(*rel)
                if (root / relative).is_file():
                    local = relative.as_posix()
            index[row["step_index"]].append({"source_uri": uri, "path_within_archive": local})
    return dict(index)


def session_creation(summary_blob, database, earliest):
    if not (summary_blob and database.is_file() and earliest):
        return None
    try:
        with connect(database) as db:
            trajectory = db.execute("SELECT data FROM trajectory_metadata_blob WHERE id='main'").fetchone()
        if not trajectory:
            return None
        stamps = [fields(descend(summary_blob, 7)), fields(descend(summary_blob, 17, 2)),
                  fields(descend(trajectory[0], 2))]
        if not stamps[0] == stamps[1] == stamps[2]:
            return None
        seconds = stamps[0][1][0]
        nanos = stamps[0].get(2, [0])[0]
        first = int(datetime.fromisoformat(earliest).timestamp())
        if not (0 <= first - seconds <= 1 and 0 <= nanos < 1_000_000_000):
            return None
        utc = datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "")
        return f"{utc}.{nanos:09d}Z"
    except (sqlite3.Error, ValueError, TypeError, KeyError, IndexError, OSError, StopIteration):
        return None


def make_markdown(path, session, rows, artifact_index, dataset):
    summary = session["summary"]
    check = session["verification"]
    artifacts = session["artifacts"]
    row_files = defaultdict(list)
    for artifact in artifacts:
        step = artifact["step_index"]
        if step is not None:
            row_files[step].append(artifact["path_within_archive"])
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(f"# {summary.get('title') or '未命名会话'}\n\n")
        stream.write(f"- UUID `{summary['conversation_id']}`\n")
        stream.write(f"- 状态 {session['status']}\n")
        stream.write(f"- 会话创建时间（元数据交叉核对，UTC） {session['created_at_utc'] or '未知'}\n")
        stream.write(f"- 最早保存步骤 {session['earliest_step_utc'] or '未知'}\n")
        stream.write(f"- 最后活动（会话索引） {summary.get('last_modified_time') or '未知'}\n")
        stream.write(f"- 所属工作区 {', '.join(session['workspace_paths']) or '未记录'}\n")
        stream.write(f"- 导出 {len(rows)} 步，其中数据库补齐 {len(check['recovered_sqlite_steps'])} 步\n")
        for label, source in (("原始日志", session["source_log"]), ("原始会话数据库", session["source_db"]),
                              ("完整 JSON 数据", dataset), ("工件目录索引", artifact_index)):
            stream.write(f"- [{label}]({relative_link(path.parent, source)})\n")
        stream.write("\n")
        for error in check["anomalies"]:
            stream.write(f"- 核验异常 {error}\n")
        for row in rows:
            index = row["step_index"]
            sections = dict(row)
            for key in ("step_index", "source", "type", "created_at", "status"):
                sections.pop(key, None)
            labels = {"USER_INPUT": "用户", "PLANNER_RESPONSE": "Agent", "GENERIC": "工具结果或通用步骤",
                      "ERROR_MESSAGE": "系统错误", "SYSTEM_MESSAGE": "系统", "CHECKPOINT": "检查点"}
            stream.write(f'<a id="step-{index}"></a>\n\n')
            stream.write(f"## 步骤 {index} · {labels.get(row['type'],row['type'])}\n\n")
            stream.write(f"`{row['type']}` · `{row['source']}` · `{row['status']}` · {row.get('created_at','')}\n\n")
            for key, label in (("content", "正文"), ("thinking", "原日志记录的思考文本"),
                               ("error", "错误"), ("tool_calls", "工具调用及原始参数"),
                               ("media", "原日志的媒体引用")):
                if key in sections:
                    stream.write(f"### {label}\n\n")
                    stream.write(text_or_json(sections.pop(key)))
            if sections:
                stream.write("### 其他结构化字段\n\n")
                stream.write(data_block(sections))
            for local in row_files[index]:
                stream.write(f"- [步骤附件或终端输出]({quote('../' + local, safe='/')})\n")
            if row_files[index]:
                stream.write("\n")
            for entry in session["media_by_step"].get(index, []):
                local = entry["path_within_archive"]
                if local:
                    stream.write(f"- [读取已归档媒体]({quote('../' + local, safe='/')})\n")
            if session["media_by_step"].get(index):
                stream.write("\n")


def verify_exports(md, dataset, original_rows, source, check):
    saved = json.loads(dataset.read_text(encoding="utf-8"))
    if saved["steps"] != original_rows:
        raise ValueError(f"JSON re-read changed the steps: {dataset}")
    if source.name == "transcript_full.jsonl" and source.exists() and not check["anomalies"]:
        restored = set(check["recovered_sqlite_steps"])
        if [row for row in saved["steps"] if row["step_index"] not in restored] != read_resilient(source)[0]:
            raise ValueError(f"JSON does not round-trip to source transcript: {source}")
    header = re.compile(r"^## 步骤 (\d+) · ")
    fence_line = re.compile(r"^(`{3,})(text|json)?\s*$")
    positions = {0, len(original_rows) // 2, len(original_rows) - 1}
    blocks = []
    current = -1
    active_fence = None
    with md.open(encoding="utf-8", newline="") as stream:
        for line in stream:
            match = header.match(line) if active_fence is None else None
            fence = fence_line.fullmatch(line)
            if fence and active_fence is None and fence[2]:
                active_fence = fence[1]
            elif fence and active_fence == fence[1] and not fence[2]:
                active_fence = None
            if match and current + 1 < len(original_rows) and int(match[1]) == original_rows[current + 1]["step_index"]:
                current += 1
                blocks.append([])
            elif blocks and current in positions:
                blocks[-1].append(line)
    if len(blocks) != len(original_rows):
        raise ValueError(f"Markdown step count differs: {md}")
    for position in positions:
        if position < 0 or not original_rows:
            continue
        row = original_rows[position]
        block = "".join(blocks[position])
        for key in ("content", "error", "thinking"):
            if row.get(key) and text_or_json(row[key]) not in block:
                raise ValueError(f"Markdown sample is incomplete: {md} #{position} {key}")
    return sorted(position for position in positions if 0 <= position < len(original_rows))


def artifact_catalog(root, grouped):
    output = root / "04_Brain_Artifacts" / "INDEX.md"
    with output.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("# Brain 工件索引\n\n原始 JSONL、分块日志仍保留在 01_Raw_Backup。这里列出另外归档的 Brain 工件。\n\n")
        for (profile, uid), files in grouped.items():
            stream.write(f"## {profile} / {uid}\n\n")
            for item in files:
                rel = Path(item["path_within_archive"]).relative_to("04_Brain_Artifacts").as_posix()
                label = rel.split("/", 1)[-1].replace("[", "\\[").replace("]", "\\]")
                stream.write(f"- [{label}]({quote(rel, safe='/')}) · {item['bytes']:,} B\n")
            stream.write("\n")
    return output


def profile_index(raw, blocked):
    summaries, indexed, secondary = {}, set(), {}
    issues = []
    database = raw / "conversation_summaries.db"
    if database.is_file() and database not in blocked:
        try:
            with connect(database) as db:
                for row in db.execute("SELECT * FROM conversation_summaries ORDER BY last_modified_time DESC"):
                    if isinstance(row["conversation_id"], str) and is_uuid(row["conversation_id"]):
                        summaries[row["conversation_id"]] = dict(row)
                has_fts = db.execute("SELECT 1 FROM sqlite_master WHERE name='conversations_fts'").fetchone()
                if has_fts:
                    indexed = {row[0] for row in db.execute("SELECT DISTINCT conversation_id FROM conversations_fts")}
        except (sqlite3.Error, OSError, ValueError, IndexError, StopIteration):
            issues.append("unsupported_summary_database")
    else:
        issues.append("summary_database_missing_or_corrupt")
    secondary_file = raw / "agyhub_summaries_proto.pb"
    if secondary_file.exists():
        try:
            for row in fields(secondary_file.read_bytes()).get(1, []):
                uid = descend(row, 1).decode("utf-8")
                if is_uuid(uid):
                    summary = descend(row, 2)
                    name = fields(summary).get(1, [b""])[0]
                    secondary[uid] = (name.decode("utf-8") if isinstance(name, bytes) else "", summary)
        except (OSError, ValueError, TypeError, IndexError):
            issues.append("unsupported_secondary_index")
    disk = {p.stem for p in (raw / "conversations").iterdir()
            if p.is_file() and is_uuid(p.stem)} if (raw / "conversations").is_dir() else set()
    logs = {p.parents[2].name for p in (raw / "brain").glob("*/.system_generated/logs/transcript*.jsonl")
            if is_uuid(p.parents[2].name)}
    ids = list(summaries) + sorted((disk | logs | secondary.keys()) - summaries.keys())
    return summaries, indexed, secondary, ids, issues


def export_archive(root, manifest, progress=None):
    raw_dir = root / "01_Raw_Backup"
    profiles = [p for p in sorted(raw_dir.iterdir()) if p.is_dir() and p.name != "SQLite_Standalone"]
    blocked = {root / warning["relative_path"] for warning in manifest.get("database_warnings", [])}
    md_dir, json_dir, brain_dir, index = (root / name for name in (
        "02_Conversations_Markdown", "03_Conversations_JSON", "04_Brain_Artifacts", "05_Project_Index"))
    for folder in (md_dir, json_dir, brain_dir, index):
        folder.mkdir(exist_ok=False)
    archive_artifacts = {}
    for raw in profiles:
        grouped = copy_artifacts(raw, brain_dir / raw.name, root, progress)
        archive_artifacts.update({(raw.name, name): value for name, value in grouped.items()})
    artifacts_md = artifact_catalog(root, archive_artifacts)
    report = {"profiles": [], "sessions": [], "brain_artifact_files": sum(map(len, archive_artifacts.values()))}
    positions = [(raw, *profile_index(raw, blocked)) for raw in profiles]
    total = sum(len(ids) for _, _, _, _, ids, _ in positions)
    position = 0
    for raw, summaries, indexed, secondary, ids, issues in positions:
        try:
            controls = check_wire_against_logs(raw)
        except (sqlite3.Error, OSError, ValueError, TypeError, StopIteration):
            controls = 0
        report["profiles"].append({"label": raw.name, "metadata_sessions": len(summaries),
                                   "indexed_sessions": len(indexed), "secondary_sessions": len(secondary),
                                   "protobuf_controls": controls, "warnings": issues})
        for uid in ids:
            name = raw.name + "--" + uid
            md_path, data_path = md_dir / (name + ".md"), json_dir / (name + ".json")
            result = export_session(root, raw, uid, summaries, secondary, ids, controls, blocked,
                                    archive_artifacts.get((raw.name, uid), []), md_path, data_path, artifacts_md)
            report["sessions"].append(result)
            position += 1
            if progress:
                progress("export", position, total)
    dump_json(index / "SESSION_VERIFICATION.json", report)
    return report


def export_session(root, raw, uid, summaries, secondary, ids, controls, blocked,
                   artifacts, md_path, data_path, artifacts_md):
    summary = dict(summaries.get(uid, {"conversation_id": uid, "title": secondary.get(uid, ("",))[0]}))
    raw_summary = summary.pop("raw_summary", None)
    if isinstance(raw_summary, bytes):
        summary["raw_summary_base64"] = base64.b64encode(raw_summary).decode("ascii")
    db_path = raw / "conversations" / (uid + ".db")
    rows, check, log, db = expected_for_uuid(raw, uid, controls, db_path in blocked)
    if uid not in summaries:
        check["anomalies"].append("session_metadata_unconfirmed")
    try:
        uris = json.loads(summary.get("workspace_uris") or "[]")
        if not isinstance(uris, list) or any(not isinstance(uri, str) for uri in uris):
            raise ValueError("invalid workspace metadata")
        workspace = [file_uri(uri) for uri in uris]
    except (TypeError, ValueError):
        workspace = []
        check["anomalies"].append("unsupported_workspace_metadata")
    if summary.get("step_count", check["sqlite_steps"]) != check["sqlite_steps"]:
        check["anomalies"].append("summary_step_count_mismatch")
    if summary.get("parent_conversation_id") and summary["parent_conversation_id"] not in ids:
        check["anomalies"].append("parent_conversation_not_found")
    media = media_index(rows, root, raw.name)
    missing_media = sum(item["path_within_archive"] is None for values in media.values() for item in values)
    if missing_media:
        check["anomalies"].append(f"media_not_found:{missing_media}")
    earliest = rows[0].get("created_at") if rows else None
    session = {
        "profile": raw.name, "summary": summary,
        "status": "FAILED" if not rows else "PARTIAL" if check["anomalies"] else "COMPLETE",
        "workspace_paths": workspace, "created_at_utc": session_creation(raw_summary, db, earliest),
        "earliest_step_utc": earliest, "source_log": str(log), "source_db": str(db), "verification": check,
        "artifacts": artifacts, "file_tool_actions": tool_actions(rows), "media_by_step": media,
    }
    dump_json(data_path, {**session, "steps": rows})
    make_markdown(md_path, session, rows, artifacts_md, data_path)
    sampled = verify_exports(md_path, data_path, rows, log, check)
    return {key: value for key, value in session.items()
            if key not in {"artifacts", "file_tool_actions", "media_by_step"}} | {
        "counts_by_type": dict(Counter(row["type"] for row in rows)), "markdown": md_path.relative_to(root).as_posix(),
        "json": data_path.relative_to(root).as_posix(), "artifact_count": len(artifacts),
        "file_action_count": len(session["file_tool_actions"]), "markdown_sampled_positions": sampled,
        "local_media_matches": sum(map(len, media.values())) - missing_media,
    }
