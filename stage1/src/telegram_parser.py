"""Публичная веб-витрина Telegram: Selenium → BeautifulSoup → pandas, без API."""

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import pandas as pd
from selenium.common.exceptions import InvalidSessionIdException

from common import load_page, keyword_hits, within_period, parse_count, note_error


CHANNELS = ["minprosrf", "minobrnaukiofficial"]
QUERIES = [
    "колледж", "техникум", "СПО", "Профессионалитет", "высшее образование",
    "вуз", "университет", "абитуриент", "поступление", "приём", "ЕГЭ", "ОГЭ",
    "10 класс", "десятый класс", "рабочие профессии", "профориентация",
    "профессиональные пробы", "трудоустройство", "Молодые профессионалы",
    "WorldSkills", "EuroSkills",
]
MOSCOW = timezone(timedelta(hours=3))
COLUMNS = [
    "post_id", "channel", "url", "published_at", "text", "views_raw", "views",
    "reactions_raw", "reactions", "media", "media_count", "album_post_ids",
    "is_forward", "collected_at", "matched_terms", "query_matches",
]


def read_telegram_message(message):
    """Одна строка = один видимый пост; все карточки альбома остаются в этой строке."""
    channel, number = message["data-post"].split("/")
    date = message.select_one("a.tgme_widget_message_date time[datetime]")
    if date is None:
        raise ValueError("У сообщения отсутствует дата публикации")
    published = datetime.fromisoformat(date["datetime"]).astimezone(MOSCOW).isoformat()
    body = message.select_one(".tgme_widget_message_text")
    views = message.select_one(".tgme_widget_message_views")
    views_raw = views.get_text(strip=True) if views else None
    album = sorted({int(a["href"].split("?")[0].rstrip("/").split("/")[-1])
                    for a in message.select(".tgme_widget_message_grouped_wrap a[href]")
                    if re.search(r"/" + re.escape(channel) + r"/\d+\?single", a["href"])})
    number = min([int(number)] + album)
    # Reactions excluded by docs/branch-plan.md.
    reactions_raw, reactions = [], []
    media = {kind: len(message.select(selector)) for kind, selector in {
        "photo": ".tgme_widget_message_photo_wrap",
        "video": ".tgme_widget_message_video_player",
        "document": ".tgme_widget_message_document_wrap",
        "audio": ".tgme_widget_message_audio",
        "voice": ".tgme_widget_message_voice",
        "sticker": ".tgme_widget_message_sticker",
    }.items()}
    return dict(
        post_id=number, channel=channel, url=f"https://t.me/{channel}/{number}",
        published_at=published, text=body.get_text(" ", strip=True) if body else "",
        views_raw=views_raw, views=parse_count(views_raw),
        # Нет блока реакций ≠ нулевое число реакций.
        reactions_raw=json.dumps(reactions_raw, ensure_ascii=False) if reactions_raw else None,
        reactions=json.dumps(reactions, ensure_ascii=False) if reactions else None,
        media=";".join(kind for kind, count in media.items() if count),
        media_count=sum(media.values()), album_post_ids=json.dumps(album),
        is_forward=message.select_one(".tgme_widget_message_forwarded_from") is not None,
        collected_at=datetime.now(MOSCOW).isoformat(timespec="seconds"),
    )


def collect_telegram(driver, config):
    """Обойти доступную ленту и локально отобрать тематические посты.

    config: start/end (ISO), terms, output_dir, pause, demo, limit.
    Необязательно: telegram_queries, telegram_channels, telegram_mode='feed' (по умолчанию).
    demo ограничивает число новых подходящих постов на канал; полный режим не имеет
    искусственного лимита. Файлы состояния позволяют продолжить прерванный запуск.
    Режим 'search' нужен только для диагностики: веб-поиск обрезает выдачу.
    Наличие удалённых постов этим обходом не проверяется.
    """
    output = Path(config["output_dir"])
    output.mkdir(parents=True, exist_ok=True)
    checkpoint = output / "telegram_checkpoint.json"
    queries = config.get("telegram_queries", QUERIES)
    channels = config.get("telegram_channels", CHANNELS)
    if config.get("telegram_mode", "feed") == "feed":
        queries = [""]
    signature = {k: config[k] for k in ("start", "end", "terms")}
    signature.update(channels=channels, queries=queries, demo=bool(config.get("demo")))
    state = {"settings": signature, "records": {}, "tasks": {}}
    if checkpoint.exists():
        state = json.loads(checkpoint.read_text(encoding="utf-8"))
        if state["settings"] != signature:
            raise ValueError("Настройки изменились: выберите новый output_dir для Telegram")

    def save():
        temporary = checkpoint.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        temporary.replace(checkpoint)
        frame = pd.DataFrame(state["records"].values(), columns=COLUMNS)
        if not frame.empty:
            frame = frame.sort_values(["channel", "post_id"]).reset_index(drop=True)
        frame.to_csv(output / "telegram.csv", index=False, encoding="utf-8-sig")
        coverage = [{k: v for k, v in task.items() if k != "ids"} | {"examined": len(task["ids"])}
                    for task in state["tasks"].values()]
        pd.DataFrame(coverage).to_csv(output / "telegram_coverage.csv", index=False, encoding="utf-8-sig")
        frame.attrs["coverage"] = coverage
        frame.attrs["scope"] = ("Обход доступной ленты с локальным тематическим отбором" if queries == [""]
                                else "Выдача веб-поиска ограничена; историческая полнота не установлена")
        return frame

    for channel in channels:
        added = 0
        for query in queries:
            base = f"https://t.me/s/{channel}"
            initial_url = base + ("?" + urlencode({"q": query}) if query else "")
            task = state["tasks"].setdefault(channel + "|" + query, {
                "channel": channel, "query": query, "next_url": initial_url,
                "pages": 0, "ids": [], "earliest": None, "latest": None,
                "without_text": 0, "parse_errors": 0, "status": "pending",
            })
            if task["status"] == "complete":
                continue
            task["status"] = "running"
            seen = set(task["ids"])
            while task["next_url"]:
                url = task["next_url"]
                try:
                    soup = load_page(driver, url, ".tgme_channel_history")
                    messages = soup.select(".tgme_widget_message[data-post]")
                    if not messages and not soup.select_one(".tme_no_messages_found"):
                        raise ValueError("Нет ни сообщений, ни явного сообщения о пустой выдаче")
                    dates, fresh = [], 0
                    for message in messages:
                        identifier = message["data-post"]
                        if identifier in seen:
                            continue
                        fresh += 1
                        seen.add(identifier)
                        try:
                            row = read_telegram_message(message)
                        except (ValueError, KeyError, TypeError) as error:
                            task["parse_errors"] += 1
                            note_error("telegram", "https://t.me/" + identifier, str(error))
                            continue
                        date = row["published_at"][:10]
                        dates.append(date)
                        task["earliest"] = min(task["earliest"] or date, date)
                        task["latest"] = max(task["latest"] or date, date)
                        task["without_text"] += not bool(row["text"])
                        hits = keyword_hits(row["text"], config["terms"])
                        if not within_period(row["published_at"], config["start"], config["end"]) or not hits:
                            continue
                        key = f"{channel}/{row['post_id']}"
                        previous = state["records"].get(key)
                        found_by = set(json.loads(previous["query_matches"])) if previous else set()
                        found_by.add(query or "[полная лента]")
                        row["matched_terms"] = json.dumps(hits, ensure_ascii=False)
                        row["query_matches"] = json.dumps(sorted(found_by), ensure_ascii=False)
                        state["records"][key] = row
                        added += previous is None
                    task["ids"] = sorted(seen)
                    task["pages"] += 1
                    older = soup.select_one("a.tme_messages_more[data-before][href]")
                    next_url = urljoin(url, older["href"]) if older else None
                    if next_url:
                        target = urlparse(next_url)
                        old_cursor = parse_qs(urlparse(url).query).get("before", [None])[0]
                        cursor = parse_qs(target.query).get("before", [None])[0]
                        if target.hostname != "t.me" or target.path != f"/s/{channel}":
                            raise ValueError("Ссылка пагинации выходит за пределы выбранного канала")
                        if not cursor or (old_cursor and int(cursor) >= int(old_cursor)) or not fresh:
                            raise ValueError("Пагинация не продвигается к более старым сообщениям")
                    if not next_url or (dates and max(dates) < config["start"]):
                        task.update(status="complete", next_url=None,
                                    stop_reason="end_of_results" if not next_url else "before_period")
                    else:
                        task["next_url"] = next_url
                    save()
                    print(f"Telegram @{channel}, «{query or 'лента'}»: "
                          f"{task['pages']} стр., {len(seen)} просмотрено, "
                          f"{len(state['records'])} тематических постов", flush=True)
                    if config.get("demo") and added >= config.get("limit", 20):
                        if task["status"] != "complete":
                            task.update(status="demo_limit", stop_reason="demo_limit")
                        break
                    time.sleep(config.get("pause", 1))
                except (PermissionError, InvalidSessionIdException) as error:
                    task.update(status="access_blocked" if isinstance(error,PermissionError) else "browser_closed", stop_reason=str(error))
                    note_error("telegram", url, str(error))
                    save()
                    raise
                except Exception as error:
                    task.update(status="error", stop_reason=str(error))
                    note_error("telegram", url, str(error))
                    save()
                    break
            if config.get("demo") and added >= config.get("limit", 20):
                break
    frame = save()
    return frame


def collect_telegram_sample(driver, config):
    """30 тематических постов/канал/год: от 31 июля назад, в пределах года.

    Дополнительное окно — от конечной даты исследования. Границы находятся по ID
    в обычной ленте; веб-поиск q не используется, поскольку ограничивает выдачу.
    Это воспроизводимая сезонная выборка, непригодная для оценки частот по годам.
    """
    output = Path(config["output_dir"])
    output.mkdir(parents=True, exist_ok=True)
    checkpoint = output / "telegram_sample_checkpoint.json"
    settings = {k: config[k] for k in ("start", "end", "terms")}
    settings["per_window"] = config.get("per_window", 30)
    settings["matcher_version"] = config.get("matcher_version", "matcher_v2")
    state = {"settings": settings, "records": {}, "windows": {}, "availability": {}}
    if checkpoint.exists():
        state = json.loads(checkpoint.read_text(encoding="utf-8"))
        state["settings"].setdefault("matcher_version", "matcher_v1")
        if state["settings"] != settings:
            raise ValueError("Для другой выборки Telegram выберите новый output_dir")

    def save():
        temporary = checkpoint.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        temporary.replace(checkpoint)
        frame = pd.DataFrame(state["records"].values(), columns=COLUMNS + ["sample_windows"])
        if not frame.empty:
            frame = frame.sort_values(["channel", "post_id"]).reset_index(drop=True)
        frame.to_csv(output / "telegram.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame(state["windows"].values()).to_csv(output / "telegram_coverage.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame(state["availability"].values()).to_csv(output / "telegram_availability.csv", index=False, encoding="utf-8-sig")
        windows = []
        for task in state["windows"].values():
            selected = [row for row in state["records"].values()
                        if row["channel"] == task["channel"] and task["cutoff"] in json.loads(row["sample_windows"])]
            windows.append(dict(
                channel=task["channel"], year=int(task["cutoff"][:4]), cutoff=task["cutoff"],
                target_n=task["target_n"], selected_n=len(selected), status=task["status"],
                window_initial_before=max(row["post_id"] for row in selected) + 1 if selected else None,
                earliest_selected=min(row["published_at"] for row in selected) if selected else None,
                latest_selected=max(row["published_at"] for row in selected) if selected else None,
                note="Старт повторения = максимальный выбранный ID + 1; цель — те же публикации, пока они доступны",
            ))
        pd.DataFrame(windows).to_csv(output / "telegram_windows.csv", index=False, encoding="utf-8-sig")
        (output / "telegram_windows.json").write_text(json.dumps(windows, ensure_ascii=False, indent=2), encoding="utf-8")
        metadata = dict(
            settings=state["settings"],
            selection="30 кандидатов на канал/год от 31 июля назад + окно до 06.10.2026; только текущий год",
            matcher_note="matcher_v1: вуз только отдельное слово; matcher_v2: также вузы/вузов/вузах",
            limitation="Сезонная целевая выборка. Частоты по годам не оцениваются; совпадение слов не является кодом охлаждения",
            availability=list(state["availability"].values()),
        )
        (output / "telegram_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return frame

    def page(channel, before=None):
        url = f"https://t.me/s/{channel}" + (f"?before={before}" if before else "")
        soup = load_page(driver, url, ".tgme_channel_history")
        rows = []
        for message in soup.select(".tgme_widget_message[data-post]"):
            try:
                rows.append(read_telegram_message(message))
            except (ValueError, KeyError, TypeError) as error:
                note_error("telegram", "https://t.me/" + message["data-post"], str(error))
        if not rows:
            raise ValueError(f"Не удалось прочитать сообщения: {url}")
        time.sleep(config.get("pause", 1.5))
        return sorted(rows, key=lambda row: row["post_id"]), soup

    for channel in CHANNELS:
        if channel not in state["availability"]:
            earliest, _ = page(channel, 20)
            latest, _ = page(channel)
            state["availability"][channel] = dict(
                channel=channel, earliest_observed=earliest[0]["published_at"],
                earliest_post_id=earliest[0]["post_id"], latest_observed=latest[-1]["published_at"],
                latest_post_id=latest[-1]["post_id"],
                note="Первые доступные публикации; отсутствие удалённых публикаций проверить нельзя",
            )
            save()
        availability = state["availability"][channel]
        for year in range(int(config["start"][:4]), int(config["end"][:4]) + 1):
            cutoffs = [min(f"{year}-07-31", config["end"])]
            if year == int(config["end"][:4]) and config["end"] > cutoffs[0]:
                cutoffs.append(config["end"])
            for cutoff in cutoffs:
                key = channel + "|" + cutoff
                task = state["windows"].setdefault(key, dict(
                    channel=channel, cutoff=cutoff, target_n=settings["per_window"],
                    selection="От даты отсечения назад; только текущий год; тематический отбор",
                    status="pending", pages=0, matched=0, earliest_examined=None, latest_examined=None,
                ))
                if task["status"] in {"complete", "before_first_observed"}:
                    continue
                if cutoff < availability["earliest_observed"][:10]:
                    task.update(status="before_first_observed", stop_reason="Раньше первой доступной публикации")
                    save()
                    continue
                try:
                    if "before" not in task:
                        low, high = availability["earliest_post_id"], availability["latest_post_id"] + 1
                        while high - low > 20:
                            middle = (low + high) // 2
                            rows, _ = page(channel, middle)
                            older = [row for row in rows if row["post_id"] < middle]
                            probe = older[-1] if older else rows[0]
                            if probe["published_at"][:10] <= cutoff:
                                low = middle
                            else:
                                high = middle
                        task["before"] = high
                        task["window_initial_before"] = high
                    task["status"] = "running"
                    while task["matched"] < settings["per_window"]:
                        rows, soup = page(channel, task["before"])
                        dates = [row["published_at"][:10] for row in rows]
                        task["earliest_examined"] = min(task["earliest_examined"] or min(dates), min(dates))
                        task["latest_examined"] = max(task["latest_examined"] or max(dates), max(dates))
                        for row in reversed(rows):
                            if not within_period(row["published_at"], max(config["start"], f"{year}-01-01"), cutoff):
                                continue
                            hits = keyword_hits(row["text"], config["terms"])
                            if settings["matcher_version"] == "matcher_v1" and not re.search(r"(?<!\w)вуз(?!\w)", row["text"].lower()):
                                hits = [term for term in hits if term.lower() != "вуз"]
                            if not hits:
                                continue
                            row_key = f"{channel}/{row['post_id']}"
                            previous = state["records"].get(row_key)
                            windows = set(json.loads(previous["sample_windows"])) if previous else set()
                            if cutoff in windows:
                                continue
                            windows.add(cutoff)
                            row.update(matched_terms=json.dumps(hits, ensure_ascii=False),
                                       query_matches='["Сезонная выборка из ленты"]',
                                       sample_windows=json.dumps(sorted(windows)))
                            state["records"][row_key] = row
                            task["matched"] += 1
                            if task["matched"] >= settings["per_window"]:
                                break
                        task["pages"] += 1
                        previous = soup.select_one("a.tme_messages_more[data-before]")
                        next_before = int(previous["data-before"]) if previous else None
                        if task["matched"] >= settings["per_window"] or not next_before or max(dates) < f"{year}-01-01":
                            task.update(status="complete", stop_reason="target_reached" if task["matched"] >= settings["per_window"] else "available_year_exhausted")
                            save()
                            break
                        if next_before >= task["before"]:
                            raise ValueError("Пагинация сезонной выборки не продвигается")
                        task["before"] = next_before
                        save()
                    print(f"Telegram sample @{channel}, {cutoff}: {task['matched']} постов, "
                          f"{task['earliest_examined']}–{task['latest_examined']}", flush=True)
                except Exception as error:
                    task.update(status="access_blocked" if isinstance(error, PermissionError) else "error", stop_reason=str(error))
                    note_error("telegram", f"https://t.me/s/{channel}", str(error))
                    save()
                    raise
    return save()
