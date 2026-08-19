# Производство карты — полный протокол

Этап B из SKILL.md, подробно: как собрать промпт, что проверять, как править,
что делает модель не так и почему.

---

## Шаблон промпта первой генерации

Четыре блока. `{в фигурных скобках}` — подставляется из спецификации и паспорта стиля.

```
Redraw this map screenshot as a stylized pseudo-3D illustrated route map of
{регион}. PRESERVE the real geography from the screenshot: exact coastline
silhouette, relative positions of settlements, and the route path.
THE ROUTE MUST BE ONE SINGLE CONTINUOUS LINE with NO branches, NO forks,
NO loops{, draw ONLY the branch that passes {ориентир} — если на скриншоте
была альтернативная ветка}. REMOVE COMPLETELY: browser UI, tabs, taskbar,
overlays, search bar, map controls, scale bar, highway numbers, the road
network, city street grids, and all map labels.

NO TEXT ANYWHERE IN THE IMAGE. No place names, no captions, no legend, no
compass, no watermark, no numbers. Text will be added separately.
Mark the waypoints with small round dots in {цвет маршрута} with a thin white
ring; the start and finish dots slightly larger. ROUTE: one bold smooth line
in {цвет маршрута}, slightly elevated above the terrain.

Add {K} tiny illustrated vignettes drawn in the same art style as the map,
placed on the terrain at their real locations like miniature 3D objects, each
SMALL (about 4-6% of image width), soft shadows, absolutely no text near them:
(1) {объект} at {место}; (2) ... Keep vignettes subtle and integrated — the map
must stay clean and readable, not cluttered.

STYLE — follow the attached reference image, it is a STYLE reference ONLY
(content comes from the screenshot): {формула стиля из паспорта}.
{FOG/LIGHT: реальная погода дня, если была характерной}
The map fills the whole {пропорция} frame.
```

**Почему «без текста» написано дважды и капсом.** Это единственная инструкция,
которую модели нарушают чаще всего: любое пояснение в скобках рядом с виньеткой
они норовят превратить в подпись на картинке. Проверено — модель однажды
подписала домик словами «Рандер кабин», превратив ремарку из промпта в лейбл.

---

## Чек-лист перед показом человеку

Проверяй молча, сам. Показывать заведомый брак — тратить чужое время.

| # | Проверка | Норма | Если не так |
|---|----------|-------|-------------|
| 1 | Линия | одна, непрерывная, без вилок и колец | ERASE-формула ниже |
| 2 | Старт/финиш | там же, где на скриншоте | точечная правка MOVE |
| 3 | География | берег узнаётся против исходника | перегенерация; проверь, что исходник вообще подан в режиме редактирования |
| 4 | Текст | нет вообще | перегенерация с усиленным NO TEXT |
| 5 | Виньетки | все из списка, ничего лишнего | ERASE лишнего, MOVE не на месте |
| 6 | Чистота | нет UI, сетки дорог, номеров | перегенерация |
| 7 | Стиль | совпадает с паспортом | проверь, подан ли эталон референсом |

---

## Формулы точечных правок

Одна правка — один вызов. Общий каркас всегда одинаковый:

```
Make ONLY this one local fix. Everything else must stay EXACTLY as it is —
same terrain, same light, same route, same vignettes, same style.
Do not redraw or move anything that is not listed.
```

**Убрать объект**
```
ERASE {объект} completely — paint plain {terrain/coastline/water} matching
the surroundings where it used to be.
```

**Убрать лишнюю ветку маршрута** (самая частая структурная правка)
```
ERASE one orange line segment. Do not draw any new lines.
THE SEGMENT: starting where {ориентир}, it runs {направление} until {ориентир}.
Erase this ENTIRE branch, paint plain terrain where it used to be.
WHAT REMAINS: exactly ONE open line: {точка} → {точка} → {точка}.
```

**Перенести**
```
Move {объект или кластер} to {новое место}. The former spot becomes plain
{terrain}. Nothing else changes.
```

**Поменять погоду/свет**
```
Keep the terrain, route and vignettes identical. Change ONLY the atmosphere:
{новое описание света или тумана}.
```

⛔ **Референс в правках не передавать.** Проверено на живом примере: попытка
исправить одну букву с приложенным эталоном вернула вместо правки копию эталона
целиком. Референс — только в первой генерации.

---

## Грабли моделей: симптом → причина → лечение

| Симптом | Почему | Что делать |
|---------|--------|-----------|
| Две линии на выезде из города | Навигатор нарисовал альтернативу, модель честно скопировала | Указать нужную ветку в промпте (спрашивается на шаге 1) |
| Маршрут замкнулся в кольцо | Модель «доводит» линию вдоль берега до старта | ERASE-формула сегмента |
| Суша превратилась в остров | Движок не умеет редактировать, использует картинку как вдохновение | Сменить движок на умеющий редактирование (см. backends.md) |
| Подписи с опечатками | Модели врут в тексте, кириллица особенно | Не лечить промптом. Генерить без текста, ставить подписи скриптом |
| Появилась подпись, которой не просили | Ремарка из промпта превратилась в лейбл | Усилить NO TEXT; пояснения к виньеткам писать как `unlabeled` |
| Виньетка уехала в море | Модель привязала объект к слову, а не к месту | MOVE-правка с ориентиром: «beside the route line at ...» |
| После правки поехал стиль | В правку передали референс | Откатиться к прошлой версии, повторить правку без референса |
| Каждая перегенерация всё меняет | Полный проход перерисовывает всё | Правки только точечные; финальный текст — программный |

---

## Подписи: как снять координаты

Координаты нормализованные: доля от ширины и от высоты, 0..1. Левый верхний
угол — (0, 0).

Практика: открой карту, прикинь положение точки на глаз в процентах. Ошибка
в 1–2% незаметна, ошибка в 10% посадит подпись в море. После первого прогона
посмотри результат и подвинь, если нужно.

Поле `dot` необязательное — рисует маркер-точку под капсулой, если модель
не нарисовала его сама или нарисовала не там.

Полезные флаги `finalize.py`:

- `--mode overlay` — если карта уже сгенерирована с подписями: скрипт найдёт
  капсулу модели и перекроет её ровной. Основной путь — `place` (по умолчанию).
- `--font-size-ratio 0.035` — крупнее подписи (доля от высоты кадра).
- `--dot-color FE9901 --text-color 303036 --capsule-color FFFFFF` — цвета.
- `--font /путь/шрифт.ttf` — свой шрифт вместо системного.
- `--no-upscale` — быстрый прогон без повышения разрешения.
- `--also-half` — дополнительно лёгкая версия в половину размера для веба.
