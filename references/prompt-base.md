# Базовый блок промпта — общий для студии стиля и производства

Этот файл читают **оба** этапа: и пробники студии стиля, и боевая генерация карты.
Здесь собрано то, что нужно **любому** скриншоту карты, независимо от стиля.

Раньше эти правила жили только в описании производства, а студия стиля собирала
промпт «по мотивам» — и наступала на те же грабли по второму разу. Один прогон
стоил девяти генераций вместо трёх: каждый дефект ловился по одному, и каждый
стоил круга на три пробника.

---

## Обязательные блоки (вставлять всегда, целиком)

### 1. Геометрия и масштаб

```
PRESERVE the real geography from the screenshot: exact coastline and river shapes,
relative positions of settlements, the route path.
KEEP THE SAME MAP SCALE AND FRAMING as the screenshot — do NOT zoom in, do NOT
crop, do NOT enlarge any single object. A lake that occupies ~5% of the screenshot
must occupy ~5% of the result. The visible area must stay the same.
```

Без блока SCALE модель «подъезжает» к самому заметному объекту: озеро раздувается
до размера моря, а маршрут перестаёт помещаться в кадр.

### 2. Рельеф — по правде местности

```
TERRAIN: {равнина / холмы / горы / плато — реальный характер местности}.
{Уточнение: what actually grows and lies there — леса, поля, болота, степь}.
Do NOT invent mountains or dramatic relief where the land is flat.
```

Модель по умолчанию рисует «атлас приключений»: всхолмья, скалы, перепады высот —
даже там, где на самом деле плоская равнина. Это прямое нарушение обещания
скилла: карта должна показывать местность, а не жанр.

**Как узнать рельеф.** Точки маршрута почти всегда известные места. Посмотри, что
там на самом деле: равнина Подмосковья и Ярославского направления — это плоскость
с лесами, перелесками и болотами; Приморье — сопки; Крым — горы у побережья
и степь севернее. Не уверен — спроси человека: он там был, он помнит. Один вопрос
дешевле трёх кругов перерисовки.

### 3. Чистка исходника

```
REMOVE COMPLETELY: browser window frame, tabs, address bar, search box, side
panels, map UI controls, zoom buttons, scale bar, attribution and copyright
lines, any overlay or picture-in-picture window.
DELETE the operating-system taskbar strip along the bottom edge — its app icons,
clock and tray must not appear anywhere in the image.
Also remove: the road network, city street grids, highway numbers and all map
labels.
```

Панель задач Windows — отдельная строка не для красоты: без неё модель честно
перерисовывает полоску с иконками и часами как часть ландшафта.

### 4. Полный запрет текста

```
NO TEXT ANYWHERE IN THE IMAGE — zero letters in any alphabet, Latin or Cyrillic,
no place names, no captions, no legend, no compass, no watermark, no numbers.
Any scribble resembling handwriting or lettering is a defect.
Text will be added separately after generation.
```

Мягкое «no text» модель нарушает: подписывает города сама, вперемешку латиницей
и кириллицей, с опечатками. Формулировка «ноль букв любого алфавита» держит лучше.

### 5. Маршрут: цвет, точки, конец линии

```
ROUTE: exactly ONE continuous line in {цвет}, from {старт} to {финиш}.
No branches, no forks, no loops.
The route ENDS at {финиш} — keep NO line and NO dot anywhere beyond it,
in particular near {назвать соседний заметный объект: город, озеро, развязку}.
Mark waypoints with exactly {N} round dots in {цвет} with a thin white ring,
and NO other dots anywhere on the map.
{цвет} is RESERVED for the route line and its dots alone: any other track, road
or river stays muted grey-brown and must not read as part of the route.
```

Три ловушки разом. Модель любит продлить линию за конечную точку к соседнему
приметному объекту (у нас маршрут обогнул озеро Неро, где человек не был);
насыпать лишних точек; и покрасить в цвет маршрута всю дорожную сеть, после чего
линия перестаёт читаться как одна.

### 6. Виньетки

```
Add {K} tiny illustrated vignettes drawn in the same art style as the map, placed
on the terrain at their real locations like miniature 3D objects, each SMALL
(about 4-6% of image width), soft shadows, absolutely no text near them:
(1) {объект} at {место}; (2) ...
Keep vignettes subtle and integrated — the map must stay clean and readable.
```

### 7. Стиль

```
STYLE — follow the attached reference image, it is a STYLE reference ONLY
(content comes from the screenshot): {формула стиля из паспорта}.
The map fills the whole {пропорция} frame.
```

---

## Порядок сборки

1. Блоки 1–5 — **всегда**, дословно, с подстановками.
2. Блок 6 — только в производстве; в пробниках студии стиля виньеток нет.
3. Блок 7 — в студии стиля вместо ссылки на эталон идёт голая формула стиля
   (эталона ещё нет), в производстве — эталон референсом.

## Чего в базовом блоке быть не должно

Пояснений в скобках вроде «(the ranger cabin, journey's end)». Модель принимает
их за подпись и рисует текстом. Пояснение — либо в отдельное предложение,
либо со словом `unlabeled`.
