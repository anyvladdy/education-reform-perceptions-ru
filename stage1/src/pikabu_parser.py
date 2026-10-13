"""Пикабу: обычные страницы тегов и постов, только первичный набор комментариев.

Проверено 07.10.2026: /tag/Колледж?page=2 и ?page=3 возвращают разные посты;
/tag/Колледж/new перенаправляет на /tag/Колледж (сначала свежее).
robots.txt разрешает обычные tag/story, запрещает API, ajax и поиск с фильтрами.
Пагинация не гарантирует полный архив: причины остановки сохраняются отдельно.
Ники/ID авторов не извлекаются; исходный текст может содержать упоминания людей.
"""

import json
import re
import time
from datetime import datetime, timezone
from itertools import count, zip_longest
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import pandas as pd
from selenium.common.exceptions import InvalidSessionIdException

from common import keyword_hits, load_page, note_error, parse_count, within_period


# Расширяем рамку отбора, а не ищем только подтверждения «охлаждения».
PIKABU_TAGS = {
    "Колледж": "выбор СПО и опыт обучения",
    "СПО": "обсуждение среднего профессионального образования",
    "Высшее образование": "ценность ВО, критика и защита университета",
    "Рабочие профессии": "престиж труда и экономические аргументы",
    "Поступление": "смена образовательных планов при поступлении",
    "ЕГЭ": "барьеры и стратегии доступа к ВО",
    "10 класс": "отбор и отказы при переходе в старшую школу",
    "9 класс": "развилка школа — колледж",
    "11 класс": "завершение школы и планы поступления",
    "ОГЭ": "экзамены и отбор после основной школы",
    "ПТУ": "историческое название и стигма рабочего образования",
    "Техникум": "альтернативное название организаций СПО",
    "Абитуриент": "советы, ожидания и пересмотр притязаний",
    "Поступление в вуз": "конкретные решения и препятствия",
    "Вуз": "аргументы в пользу и против университетской траектории",
    "Университет": "ценность диплома и опыт высшего образования",
    "Профориентация": "советы и институциональное направление выбора",
    "Профессионалитет": "риторика реформы СПО после 2022 года",
    "Бюджетные места": "конкуренция и материальная доступность",
    "Платное образование": "стоимость и вынужденный пересмотр планов",
}

PIKABU_CONTEXT = ["колледж", "техникум", "вуз", "университет", "образован", "пту", "спо",
                  "школ", "егэ", "огэ", "абитуриент", "училищ", "диплом", "професси", "класс"]
PIKABU_CHOICE = [
    "поступ", "прием", "отбор", "конкурс", "зачисл", "балл", "бюджет", "платн", "стоим",
    "отказ", "не берут", "не приняли", "не прош", "передум", "выб", "совет", "профориент",
    "нужен", "нужно", "диплом", "престиж", "успех", "зарплат", "зараб", "востреб",
    "трудоустр", "работ", "кадр", "Профессионалитет", "Молодые профессионалы", "WorldSkills",
    "EuroSkills", "разочаров", "пожалел", "бесполез", "ценност", "статус", "мечт", "хочу",
    "хотел", "застав", "сокращ", "доступ", "возможност", "перевод", "перевест",
]

PIKABU_COLUMNS = [
    "row_type", "record_id", "post_id", "parent_comment_id", "url", "date",
    "title", "text", "tags", "rating", "total_comments", "collected_comments",
    "matched_terms", "collected_at", "discovery_method", "discovery_tags",
    "comments_scope",
]


def _pk_text(node, selector):
    element = node.select_one(selector)
    return element.get_text("\n", strip=True) if element else ""


def _pk_date(node):
    element = node.select_one("time[datetime]")
    return element.get("datetime", "") if element else ""


def _pk_topic(text):
    """Образовательный контекст И выбор/оценка/барьер; знак отношения не задан."""
    return bool(keyword_hits(text, PIKABU_CONTEXT) and keyword_hits(text, PIKABU_CHOICE))


def _pk_period(date):
    year = str(date)[:4]
    return "2018" if year == "2018" else "2019–2021" if "2019" <= year <= "2021" else "2022–2026"


def _pk_save_json(path, value):
    """Атомарная запись с коротким повтором при временной блокировке OneDrive."""
    temporary = path.with_suffix(".tmp")
    for attempt in range(5):
        try:
            temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.3 * (attempt + 1))


def _pk_url(url):
    parts = urlsplit(url)
    if parts.netloc not in {"pikabu.ru", "www.pikabu.ru"} or not re.fullmatch(
        r"/story/[^/]+_\d+", parts.path
    ):
        return None
    return urlunsplit(("https", "pikabu.ru", parts.path, "", ""))


def parse_pikabu_post(soup, url, config, discovery=None):
    """Один пост + комментарии, уже находящиеся в DOM; кнопки не нажимаются."""
    post_id = url.rsplit("_", 1)[-1]
    post = soup.select_one(f'article.story[data-story-id="{post_id}"]')
    if post is None:
        raise ValueError("На странице нет ожидаемого поста")
    date = _pk_date(post)
    if not date:
        raise ValueError("У поста отсутствует time[datetime]")
    if not within_period(date, config["start"], config["end"]):
        return []

    title = _pk_text(post, ".story__title-link")
    text = "\n\n".join(x.get_text("\n", strip=True) for x in
                       post.select(".story-block_type_text"))
    if not text:
        text = _pk_text(post, ".story__content-inner")
    tags = list(dict.fromkeys(x.get_text(" ", strip=True)
                             for x in post.select(".story__tags a.tags__tag")))
    hits = keyword_hits("\n".join([title, text, *tags]), config["terms"])
    if not hits or not _pk_topic("\n".join([title, text, *tags])):
        return []

    collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    discovery = discovery or {"method": "seed", "tags": []}
    common = dict(
        post_id=post_id, title=title, tags=" | ".join(tags),
        total_comments=parse_count(post.get("data-comments")),
        collected_at=collected_at, discovery_method=discovery["method"],
        discovery_tags=" | ".join(discovery["tags"]),
        comments_scope="первичный DOM без раскрытия; только даты внутри периода",
    )
    comments, seen = [], set()
    for comment in soup.select('.comment[id^="comment_"]'):
        related_post = re.search(r"(?:^|;)sid=(\d+)(?:;|$)", comment.get("data-meta", ""))
        if related_post and related_post.group(1) != post_id:
            continue
        comment_id = comment.get("data-id") or comment["id"].removeprefix("comment_")
        if comment_id in seen:
            continue
        seen.add(comment_id)
        comment_url = f"{url}?cid={comment_id}"
        body = comment.find(class_="comment__body", recursive=False)
        comment_date = _pk_date(body) if body else ""
        if not comment_date:
            note_error("pikabu", comment_url, "Комментарий без даты: не включён")
            continue
        if not within_period(comment_date, config["start"], config["end"]):
            continue
        # pid — родительский КОММЕНТАРИЙ; aid/said — авторы, их не сохраняем.
        parent = re.search(r"(?:^|;)pid=(\d+)(?:;|$)", comment.get("data-meta", ""))
        comment_text = _pk_text(body, ".comment__content")
        comments.append(dict(
            common, row_type="comment", record_id=f"comment:{comment_id}",
            parent_comment_id=parent.group(1) if parent and parent.group(1) != "0" else None,
            url=comment_url, date=comment_date, text=comment_text,
            rating=parse_count(_pk_text(body, ".comment__rating-count")),
            matched_terms=" | ".join(keyword_hits(comment_text, config["terms"])),
        ))
    rows = [dict(
        common, row_type="post", record_id=f"post:{post_id}", parent_comment_id=None,
        url=url, date=date, text=text,
        rating=parse_count(_pk_text(post, ".story__rating-count")),
        matched_terms=" | ".join(hits),
    )] + comments
    for row in rows:
        row["collected_comments"] = len(comments)
    return rows


def discover_pikabu(driver, config):
    """Пагинация тегов; не выдаём окончание доступной ленты за полный архив."""
    candidates, coverage, audit = {}, [], []
    tags = config.get("pikabu_tags", list(PIKABU_TAGS))
    max_pages = config.get("pikabu_max_pages", 1 if config.get("demo") else None)
    max_pages = int(max_pages) if max_pages is not None else None
    pause = max(3.0, float(config.get("pause", 3)))
    cache_dir = Path(config["output_dir"]) / "pikabu_discovery"
    cache_dir.mkdir(parents=True, exist_ok=True)
    for tag in tags:
        # Один небольшой JSON на тег: перезапуск читает найденные ссылки с диска.
        cache_file = cache_dir / f"{quote(tag, safe='')}.json"
        cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
        seen_ids, failures, same_pages, old_pages = set(), 0, 0, 0
        first_date, last_date, pages = "", "", 0
        reason = "достигнут заданный предел страниц; покрытие неполное"
        page_numbers = config.get("pikabu_page_numbers", {}).get(
            tag, count(1) if max_pages is None else range(1, max_pages + 1))
        for page in page_numbers:
            if (Path(config["output_dir"]) / "STOP_PIKABU").exists():
                raise KeyboardInterrupt("Остановка по файлу STOP_PIKABU; прогресс сохранён")
            url = f"https://pikabu.ru/tag/{quote(tag, safe='')}?page={page}"
            cached = str(page) in cache
            try:
                if not cached:
                    soup = load_page(driver, url, "article.story, #search-header, .stories-feed")
                    # Реклама без time/заголовка не входит в архивные карточки.
                    cache[str(page)] = []
                    for card in soup.select("article.story[data-story-id]"):
                        link = card.select_one(".story__title-link[href]")
                        if not link or not _pk_date(card):
                            continue
                        text = "\n".join(x.get_text(" ", strip=True) for x in
                                         card.select(".story__title, .story-block_type_text, .story__tags"))
                        more = card.select_one(".story__read-more")
                        incomplete = bool(more and "display: none" not in more.get("style", ""))
                        incomplete = incomplete or not card.select_one(".story-block_type_text")
                        decision = ("keep_incomplete_card" if incomplete else
                                    "keep_topic" if _pk_topic(text) else "excluded_no_choice_context")
                        cache[str(page)].append(dict(id=card["data-story-id"], date=_pk_date(card),
                                                    url=link["href"], title=link.get_text(" ", strip=True),
                                                    decision=decision))
                    _pk_save_json(cache_file, cache)
                cards = cache[str(page)]
                if not cards:
                    failures += 1
                    if failures >= 3:
                        reason = "три страницы без датированных постов; граница архива не доказана"
                        break
                    if not cached:
                        time.sleep(pause)
                    continue
                failures = 0
                pages += 1
                dates, ids = [], set()
                for card in cards:
                    post_id = card["id"]
                    ids.add(post_id)
                    date = card["date"]
                    dates.append(date)
                    # Дата карточки только для навигации; в базе будет дата страницы поста.
                    link = _pk_url(card["url"])
                    in_period = config["start"] <= date[:10] <= config["end"]
                    decision = card.get("decision", "keep_legacy_card")
                    audit.append(dict(tag=tag, page=page, post_id=post_id, url=link, date=date,
                                      title=card.get("title", ""),
                                      decision=decision if in_period else "outside_period"))
                    if not link or not in_period or decision.startswith("excluded"):
                        continue
                    if link not in candidates:
                        candidates[link] = {"method": "tag_pages", "tags": [], "date": date}
                    if tag not in candidates[link]["tags"]:
                        candidates[link]["tags"].append(tag)
                first_date = max([first_date, *dates])
                last_date = min([last_date, *dates]) if last_date else min(dates)
                same_pages = same_pages + 1 if ids <= seen_ids else 0
                seen_ids.update(ids)
                old_pages = old_pages + 1 if all(d[:10] < config["start"] for d in dates) else 0
                if old_pages >= 2:
                    reason = "две последовательные страницы старше начала периода"
                    break
                if same_pages >= 3:
                    reason = "три страницы не добавили новых ID; покрытие неполное"
                    break
            except (PermissionError, InvalidSessionIdException):
                raise  # CAPTCHA / ограничение доступа: остановка, без обхода защиты.
            except Exception as error:
                note_error("pikabu", url, str(error))
                failures += 1
                if failures >= 3:
                    reason = "три последовательные ошибки; обход тега остановлен"
                    break
            if not cached:
                time.sleep(pause)
        coverage.append(dict(tag=tag, pages=pages, unique_posts=len(seen_ids),
                             newest_date=first_date, oldest_date=last_date, stop_reason=reason))
        pd.DataFrame(coverage).to_csv(Path(config["output_dir"]) / "pikabu_coverage.csv",
                                     index=False, encoding="utf-8-sig")
        pd.DataFrame(audit).to_csv(Path(config["output_dir"]) / "pikabu_discovery_audit.csv",
                                  index=False, encoding="utf-8-sig")
        if config.get("verbose", True):
            print(f"Пикабу: {tag} — {pages} стр., {len(seen_ids)} постов; {reason}", flush=True)
    for raw in config.get("seed_urls", []):
        url = _pk_url(raw)
        if url:
            if url in candidates:
                candidates[url]["method"] = "tag_pages; seed"
            else:
                candidates[url] = {"method": "seed", "tags": []}
        else:
            note_error("pikabu", raw, "Пропущена ссылка, не являющаяся страницей поста")
    # Исторические контрольные примеры не вытесняются свежими постами в demo.
    seeds = {_pk_url(raw): candidates[_pk_url(raw)] for raw in config.get("seed_urls", [])
             if _pk_url(raw) in candidates}
    return {**seeds, **candidates}


def collect_pikabu(driver, config):
    """Возвращает DataFrame. Продолжение по checkpoint в отдельной папке запуска."""
    output = Path(config["output_dir"])
    output.mkdir(parents=True, exist_ok=True)
    checkpoint = output / "pikabu_checkpoint.json"
    signature = {key: config.get(key) for key in ("start", "end", "terms", "pikabu_tags", "seed_urls", "sample")}
    signature["selection_version"] = 2
    state = {"signature": signature, "rows": [], "done": [], "audit": []}
    if checkpoint.exists():
        saved = json.loads(checkpoint.read_text(encoding="utf-8"))
        if saved.get("signature") != signature:
            raise ValueError("Изменились параметры Пикабу: выберите новую output_dir")
        state = saved
    candidates = config["pikabu_candidates"] if "pikabu_candidates" in config else discover_pikabu(driver, config)
    done = set(state["done"])
    quotas = config.get("period_quotas", {})
    counts = {period: sum(row["row_type"] == "post" and _pk_period(row["date"]) == period
                          for row in state["rows"]) for period in quotas}
    limit = config.get("limit")
    processed = 0
    for url, discovery in candidates.items():
        if (output / "STOP_PIKABU").exists():
            raise KeyboardInterrupt("Остановка по файлу STOP_PIKABU; прогресс сохранён")
        if url in done:
            continue
        period = _pk_period(discovery.get("date", ""))
        if discovery.get("date") and period in quotas and counts[period] >= quotas[period]:
            continue
        if limit is not None and processed >= int(limit):
            note_error("pikabu", url, f"Достигнут лимит {limit} новых проверенных постов; сбор неполный")
            break
        try:
            soup = load_page(driver, url, "article.story[data-page='true']")
            rows = parse_pikabu_post(soup, url, config, discovery)
            state["rows"].extend(rows)
            if rows and _pk_period(rows[0]["date"]) in counts:
                counts[_pk_period(rows[0]["date"])] += 1
            state["audit"].append(dict(url=url, decision="kept" if rows else "excluded_period_or_topic",
                                       rows=len(rows), collected_at=datetime.now(timezone.utc).isoformat()))
            done.add(url)
            state["done"] = sorted(done)
            # Запись после каждого поста: перезапуск не теряет уже собранные строки.
            _pk_save_json(checkpoint, state)
        except (PermissionError, InvalidSessionIdException):
            raise
        except Exception as error:
            note_error("pikabu", url, str(error))
        processed += 1
        time.sleep(max(3.0, float(config.get("pause", 3))))
    frame = pd.DataFrame(state["rows"], columns=PIKABU_COLUMNS)
    frame = frame.drop_duplicates("record_id").reset_index(drop=True)
    for field in ["rating", "total_comments", "collected_comments"]:
        frame[field] = pd.to_numeric(frame[field], errors="coerce").astype("Int64")
    frame.to_csv(output / "pikabu.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(state["audit"]).to_csv(output / "pikabu_post_audit.csv", index=False, encoding="utf-8-sig")
    return frame


def collect_pikabu_sample(driver, config):
    """Воспроизводимая целевая выборка; квоты не превращают её в случайную."""
    config = dict(config, sample=True, limit=None)
    config.setdefault("pikabu_tags", [list(PIKABU_TAGS)[i] for i in [0, 1, 6, 10, 11, 17]])
    config.setdefault("period_quotas", {"2018": 60, "2019–2021": 60, "2022–2026": 60})
    config.setdefault("pikabu_max_pages", 500)
    if config["pikabu_max_pages"] is None:
        config["pikabu_max_pages"] = 500  # У выборки конечная сетка; полный обход — collect_pikabu.
    # Пять фиксированных опорных страниц добавляют обсуждение ценности ВО и труда.
    # Счётчик постов на сайте не задаёт границу архива; покрытие проверяем по датам.
    extra_pages = config.get("sample_extra_pages", {
        "Высшее образование": [1, 31, 61, 91, 121],
        "Рабочие профессии": [1, 31, 61, 91, 121],
    })
    config["pikabu_tags"] = list(dict.fromkeys([*config["pikabu_tags"], *extra_pages]))
    step = int(config.get("sample_page_step", 10))
    selected = {tag: list(range(1, config["pikabu_max_pages"] + 1, step))
                for tag in config["pikabu_tags"]}
    selected.update(extra_pages)
    plan_file = Path(config["output_dir"]) / "pikabu_sample_plan.json"
    saved_plan = json.loads(plan_file.read_text(encoding="utf-8")) if plan_file.exists() else None
    if saved_plan:
        selected = saved_plan["planned_pages"]
        step = saved_plan["page_step"]
    initial_selected = {tag: set(pages) for tag, pages in selected.items()}
    config["pikabu_page_numbers"] = selected
    candidates = discover_pikabu(driver, config)
    cache_dir = Path(config["output_dir"]) / "pikabu_discovery"
    # Добор соседних страниц для этапов, которым систематического шага не хватило.
    midpoints = {"2018": "2018-07-01", "2019–2021": "2020-07-01", "2022–2026": "2024-07-01"}
    for period, quota in config["period_quotas"].items():
        if saved_plan:
            break  # При продолжении сохраняем план страниц, а не формируем новый.
        available = sum(_pk_period(item.get("date", "")) == period for item in candidates.values())
        if available >= 2 * quota:
            continue
        target = datetime.fromisoformat(midpoints[period])
        for tag in config["pikabu_tags"]:
            if tag in extra_pages:
                continue
            cache = json.loads((cache_dir / f"{quote(tag, safe='')}.json").read_text(encoding="utf-8"))
            dated = [(int(page), rows[len(rows)//2]["date"][:10])
                     for page, rows in cache.items() if rows and int(page) in initial_selected[tag]]
            if not dated:
                continue
            anchor = min(dated, key=lambda item: abs((datetime.fromisoformat(item[1]) - target).days))[0]
            selected[tag] = sorted(set(selected[tag]) | set(range(max(1, anchor-4), anchor+6)))
            # Между последней непустой и первой пустой страницей год мог быть пропущен.
            last_page = max(page for page, _ in dated)
            empty_after = [int(page) for page, rows in cache.items()
                           if not rows and int(page) > last_page and int(page) in initial_selected[tag]]
            if empty_after and midpoints[period] < min(date for _, date in dated):
                selected[tag] = sorted(set(selected[tag]) | set(range(last_page+1, min(empty_after))))
    candidates = discover_pikabu(driver, config)
    # Чередуем годы, чтобы поздние годы не заняли всю квоту большого этапа.
    years = {str(year): [] for year in range(2018, 2027)}
    seeds = []
    for url, item in candidates.items():
        if item.get("date", "")[:4] in years:
            years[item["date"][:4]].append((url, item))
        else:
            seeds.append((url, item))
    ordered = seeds + [pair for batch in zip_longest(*years.values()) for pair in batch if pair]
    for _, item in ordered:
        item["method"] = item["method"].replace("tag_pages", "systematic_tag_pages_with_topup")
    config["pikabu_candidates"] = dict(ordered)
    _pk_save_json(plan_file, {"page_step": step, "quotas": config["period_quotas"],
                             "planned_pages": selected, "random_sample": False})
    return collect_pikabu(driver, config)
