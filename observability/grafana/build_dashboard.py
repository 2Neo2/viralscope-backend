"""Собирает дашборд Grafana «API overview»: observability/grafana/dashboards/api-overview.json.

Дашборд описан здесь, кодом, а JSON — результат. Так панели легко менять и смотреть в диффе:
    make dashboard     (или python3 observability/grafana/build_dashboard.py)
Grafana сама подхватит новый JSON примерно за 10 секунд — перезапускать её не нужно.

Правки, сделанные мышкой в интерфейсе Grafana, при следующей сборке пропадут — переносите их сюда.
Только стандартная библиотека Python: venv не нужен.
"""

import json
import sys
from pathlib import Path

DEFAULT_OUT = Path(__file__).resolve().parent / "dashboards" / "api-overview.json"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
DS = {"type": "loki", "uid": "loki"}
REQ = '{service="api"} | json | event="request_finished"'
DUR = f'{REQ} | unwrap duration_ms | __error__=""'
# Для таблицы маршрутов: 404 на несуществующие адреса — не маршруты API, а мусор
ROUTES = f"{REQ} | status != 404"
ROUTES_DUR = f'{ROUTES} | unwrap duration_ms | __error__=""'
# Медленные SQL: от любого Python-сервиса (api, worker, beat), см. log_slow_queries в app/core/db.py
SLOW = '{service=~"api|migrate|worker|beat"} | json | event="slow_query"'
SLOW_DUR = f'{SLOW} | unwrap duration_ms | __error__=""'


def target(ref, expr, legend="", instant=False):
    return {
        "refId": ref,
        "datasource": DS,
        "expr": expr,
        "legendFormat": legend,
        "queryType": "instant" if instant else "range",
        "editorMode": "code",
    }


def stat(pid, title, x, expr, unit, thresholds, description):
    return {
        "id": pid,
        "type": "stat",
        "title": title,
        "description": description,
        "datasource": DS,
        "gridPos": {"h": 4, "w": 6, "x": x, "y": 0},
        "targets": [target("A", expr, instant=True)],
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": "background",
            "graphMode": "none",
            "textMode": "value",
            "justifyMode": "center",
        },
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "decimals": 0 if unit != "ms" else 1,
                "noValue": "0",
                "color": {"mode": "thresholds"},
                "thresholds": {"mode": "absolute", "steps": thresholds},
            },
            "overrides": [],
        },
    }


green = {"color": "green", "value": None}
panels = [
    stat(
        1,
        "Запросов за период",
        0,
        f"sum(count_over_time({REQ} [$__range]))",
        "short",
        [{"color": "blue", "value": None}],
        "Все запросы к API за выбранный период (кроме успешных /health — они пишутся в debug).",
    ),
    stat(
        2,
        "Ошибок 5xx",
        6,
        f"sum(count_over_time({REQ} | status >= 500 [$__range]))",
        "short",
        [green, {"color": "red", "value": 1}],
        "Ошибки сервера. Должно быть 0 — любая цифра здесь требует разбора в панели «Последние ошибки».",
    ),
    stat(
        3,
        "Ответов 4xx",
        12,
        f"sum(count_over_time({REQ} | status >= 400 | status < 500 [$__range]))",
        "short",
        [green, {"color": "orange", "value": 50}],
        "Ошибки клиента: неверные данные, нет доступа, не найдено. Резкий рост — повод проверить фронтенд.",
    ),
    stat(
        4,
        "Среднее время ответа",
        18,
        f"avg(avg_over_time({DUR} [$__range]))",
        "ms",
        [green, {"color": "orange", "value": 300}, {"color": "red", "value": 1000}],
        "Среднее время обработки запроса внутри API (поле duration_ms).",
    ),
    {
        "id": 5,
        "type": "timeseries",
        "title": "Запросы в минуту",
        "description": "Сколько запросов пришло за каждую минуту. "
        "Всплески — рассылки, открытие потока, боты.",
        "datasource": DS,
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 4},
        "interval": "1m",
        "targets": [target("A", f"sum(count_over_time({REQ} [1m]))", "запросов в минуту")],
        "options": {
            "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
            "tooltip": {"mode": "single", "sort": "none"},
        },
        "fieldConfig": {
            "defaults": {
                "unit": "short",
                "color": {"mode": "fixed", "fixedColor": "blue"},
                # Столбики по минутам: линия со сглаживанием рисовала «горку» там, где был один всплеск
                "custom": {
                    "drawStyle": "bars",
                    "fillOpacity": 80,
                    "lineWidth": 1,
                    "showPoints": "never",
                    "spanNulls": False,
                },
            },
            "overrides": [],
        },
    },
    {
        "id": 6,
        "type": "timeseries",
        "title": "Ответы по статусам",
        "description": "Сколько ответов каждого класса в минуту. 5xx должно быть около нуля.",
        "datasource": DS,
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 4},
        "interval": "1m",
        "targets": [
            target("A", f"sum(count_over_time({REQ} | status < 400 [1m]))", "2xx–3xx"),
            target("B", f"sum(count_over_time({REQ} | status >= 400 | status < 500 [1m]))", "4xx"),
            target("C", f"sum(count_over_time({REQ} | status >= 500 [1m]))", "5xx"),
        ],
        "options": {
            "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
        "fieldConfig": {
            "defaults": {
                "unit": "short",
                "custom": {
                    "drawStyle": "bars",
                    "fillOpacity": 80,
                    "lineWidth": 1,
                    "stacking": {"mode": "normal", "group": "A"},
                    "showPoints": "never",
                },
            },
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": name},
                    "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": color}}],
                }
                for name, color in (("2xx–3xx", "green"), ("4xx", "orange"), ("5xx", "red"))
            ],
        },
    },
    {
        "id": 7,
        "type": "table",
        "title": "Самые медленные эндпоинты",
        "description": "Топ-10 маршрутов по среднему времени ответа (без 404). "
        "p95 — 95% запросов быстрее этого.",
        "datasource": DS,
        "gridPos": {"h": 9, "w": 24, "x": 0, "y": 12},
        "targets": [
            target("A", f"topk(10, avg by (path) (avg_over_time({ROUTES_DUR} [$__range])))", instant=True),
            target("B", f"quantile_over_time(0.95, {ROUTES_DUR} [$__range]) by (path)", instant=True),
            target("C", f"sum by (path) (count_over_time({ROUTES} [$__range]))", instant=True),
        ],
        "transformations": [
            {"id": "merge", "options": {}},
            {
                "id": "filterByValue",
                "options": {
                    "type": "include",
                    "match": "any",
                    "filters": [{"fieldName": "Value #A", "config": {"id": "isNotNull", "options": {}}}],
                },
            },
            {
                "id": "organize",
                "options": {
                    "excludeByName": {"Time": True},
                    "indexByName": {"path": 0, "Value #A": 1, "Value #B": 2, "Value #C": 3},
                    "renameByName": {
                        "path": "Маршрут",
                        "Value #A": "Среднее, мс",
                        "Value #B": "p95, мс",
                        "Value #C": "Запросов",
                    },
                },
            },
            {"id": "sortBy", "options": {"sort": [{"field": "Среднее, мс", "desc": True}]}},
        ],
        "options": {"showHeader": True, "cellHeight": "sm"},
        "fieldConfig": {
            "defaults": {"decimals": 1, "custom": {"align": "auto"}},
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "Запросов"},
                    "properties": [{"id": "decimals", "value": 0}],
                },
                {
                    "matcher": {"id": "byRegexp", "options": "Среднее, мс|p95, мс"},
                    "properties": [
                        {"id": "unit", "value": "ms"},
                        {
                            "id": "custom.cellOptions",
                            "value": {"type": "color-background", "mode": "gradient"},
                        },
                        {
                            "id": "thresholds",
                            "value": {
                                "mode": "absolute",
                                "steps": [
                                    green,
                                    {"color": "orange", "value": 300},
                                    {"color": "red", "value": 1000},
                                ],
                            },
                        },
                    ],
                },
            ],
        },
    },
    {
        "id": 8,
        "type": "logs",
        "title": "Последние ошибки и предупреждения",
        "description": "Ответы 4xx и 5xx и все события уровня warning/error. "
        "Request ID отсюда — в поле наверху.",
        "datasource": DS,
        "gridPos": {"h": 10, "w": 24, "x": 0, "y": 21},
        "targets": [
            target(
                "A",
                '{service="api", level=~"warning|error"} | json'
                ' | line_format "{{.status}} {{.method}} {{.path}}  {{.event}}  request_id={{.request_id}}'
                ' {{.error_type}}"',
            )
        ],
        "options": {
            "showTime": True,
            "wrapLogMessage": True,
            "sortOrder": "Descending",
            "enableLogDetails": True,
            "dedupStrategy": "none",
            "prettifyLogMessage": False,
        },
    },
    {
        "id": 9,
        "type": "logs",
        "title": "Всё о запросе: $request_id",
        "description": "Вставьте request_id из обращения клиента "
        "или из заголовка X-Request-ID в поле наверху.",
        "datasource": DS,
        "gridPos": {"h": 10, "w": 24, "x": 0, "y": 31},
        "targets": [target("A", '{service=~".+"} | json | request_id!="" | request_id="$request_id"')],
        "options": {
            "showTime": True,
            "wrapLogMessage": True,
            "sortOrder": "Ascending",
            "enableLogDetails": True,
            "dedupStrategy": "none",
            "prettifyLogMessage": True,
        },
    },
    {
        "id": 10,
        "type": "table",
        "title": "Медленные запросы к базе",
        "description": "SQL-запросы дольше VS_DB_SLOW_QUERY_MS (200 мс) за период: "
        "сколько раз, среднее и максимум. "
        "Значения параметров в лог не попадают — только текст запроса с $1, $2.",
        "datasource": DS,
        "gridPos": {"h": 9, "w": 24, "x": 0, "y": 41},
        "targets": [
            target("A", f"sum by (statement) (count_over_time({SLOW} [$__range]))", instant=True),
            target("B", f"avg by (statement) (avg_over_time({SLOW_DUR} [$__range]))", instant=True),
            target("C", f"max by (statement) (max_over_time({SLOW_DUR} [$__range]))", instant=True),
        ],
        "transformations": [
            {"id": "merge", "options": {}},
            {
                "id": "organize",
                "options": {
                    "excludeByName": {"Time": True},
                    "indexByName": {"statement": 0, "Value #A": 1, "Value #B": 2, "Value #C": 3},
                    "renameByName": {
                        "statement": "Запрос",
                        "Value #A": "Раз",
                        "Value #B": "Среднее, мс",
                        "Value #C": "Максимум, мс",
                    },
                },
            },
            {"id": "sortBy", "options": {"sort": [{"field": "Раз", "desc": True}]}},
        ],
        "options": {"showHeader": True, "cellHeight": "sm"},
        "fieldConfig": {
            "defaults": {"decimals": 0, "custom": {"align": "auto"}},
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "Запрос"},
                    "properties": [
                        {"id": "custom.width", "value": 900},
                        {"id": "custom.cellOptions", "value": {"type": "auto", "wrapText": True}},
                    ],
                },
                {
                    "matcher": {"id": "byRegexp", "options": "Среднее, мс|Максимум, мс"},
                    "properties": [
                        {"id": "unit", "value": "ms"},
                        {
                            "id": "custom.cellOptions",
                            "value": {"type": "color-background", "mode": "gradient"},
                        },
                        {
                            "id": "thresholds",
                            "value": {
                                "mode": "absolute",
                                "steps": [
                                    {"color": "orange", "value": None},
                                    {"color": "red", "value": 1000},
                                ],
                            },
                        },
                    ],
                },
            ],
        },
    },
    {
        "id": 11,
        "type": "logs",
        "title": "Медленные запросы к базе: последние",
        "description": "Каждый медленный запрос с request_id — вставьте его в поле наверху, "
        "чтобы увидеть весь запрос API, в котором он выполнялся.",
        "datasource": DS,
        "gridPos": {"h": 9, "w": 24, "x": 0, "y": 50},
        "targets": [
            target(
                "A", SLOW + ' | line_format "{{.duration_ms}} мс  {{.statement}}  request_id={{.request_id}}"'
            )
        ],
        "options": {
            "showTime": True,
            "wrapLogMessage": True,
            "sortOrder": "Descending",
            "enableLogDetails": True,
            "dedupStrategy": "none",
            "prettifyLogMessage": False,
        },
    },
]

dashboard = {
    "uid": "api-overview",
    "title": "API overview",
    "description": (
        "Состояние API ViralScope по логам из Loki: нагрузка, ошибки, медленные маршруты и SQL, "
        "поиск по request_id."
    ),
    "tags": ["viralscope", "api", "logs"],
    "timezone": "browser",
    "editable": True,
    "graphTooltip": 1,
    "refresh": "30s",
    "time": {"from": "now-1h", "to": "now"},
    "schemaVersion": 39,
    "version": 1,
    "templating": {
        "list": [
            {
                "type": "textbox",
                "name": "request_id",
                "label": "request_id",
                "description": "ID запроса из заголовка X-Request-ID или из ответа с ошибкой",
                "query": "",
                "current": {"text": "", "value": ""},
                "hide": 0,
            }
        ]
    },
    "annotations": {"list": []},
    "links": [],
    "panels": panels,
}

OUT.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"saved {OUT} ({len(panels)} panels)")
