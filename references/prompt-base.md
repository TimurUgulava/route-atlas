# Промпты движка для route-atlas v2

В v2 у движка две задачи: покраска базы и виньетки. Оба шаблона проверены на
живых прогонах. Формулировки можно адаптировать (например, при провале гейта
дрейфа), но три вещи неизменны:

1. в покраску базы **не передаётся референс-картинка** — только формула стиля
   словами (живой замер: с референсом-картинкой совпадение географии 0.37,
   без него 0.84);
2. виньетке референсом служит **только покрашенная база этой же карты**;
3. **ни в одной генерации нет текста** — подписи ставит finalize.py.

---

## 1. Покраска базы (шаг 4.2)

Вход — рендер рельефа `terrain.png`, режим **редактирования** (движок должен
уметь его — см. backends.md). Блок `{STYLE}` — формула из паспорта стиля
пользователя, словами.

```
Repaint the surface of this exact relief map. This is a RETEXTURE, not a
redraw: the output must be THIS SAME map, same framing, same scale, with every
coastline, bay, island, ridge, valley, river and lake in exactly the same
position, pixel-for-pixel. Treat the input as a locked stencil you are only
allowed to paint over.

Style to apply (described in words, no reference image):
{STYLE — формула из паспорта, например: hand-painted illustrated atlas in
oils — expressive visible brushstrokes; layered greens on forested hills;
warm sunlit valleys; narrow pale-sand beaches exactly along the existing
coastline; rich teal sea with soft depth gradation; warm low northwest sun,
soft shadows in valleys; very light atmospheric haze only in the extreme
corners, never covering the coastline.}

Forbidden: changing any geography; adding or removing islands, bays, mountains,
rivers or lakes; roads or trails of any kind; text of any kind; labels;
route lines; markers; icons; compass; legend; grid; borders; watermark; sky;
horizon. Top-down view preserved.
```

После покраски — обязательный `drift_check.py`. Известный мелкий дефект:
модель любит дорисовать тропинки по долинам — строка «roads or trails of any
kind» в Forbidden обязательна.

---

## 2. Виньетки (шаг 5.2)

По одной на вызов; серию веди в одном диалоге движка (единство руки — у MCP
это conversation с историей, у generate.py — референсом клади первую удачную
виньетку в дополнение к базе). Первой генерации референсом — покрашенная база
(`base-approved.png`): виньетке это безопасно, географии в ней нет.

```
The reference image shows the painting style and palette of an illustrated
storybook map. Paint a single object in EXACTLY that style — same colors,
same brushwork, same storybook children's-atlas feel:
{ОБЪЕКТ: 1–2 предложения — что это, ракурс, куда смотрит}.
Three-quarter aerial view seen slightly from above (bird's-eye storybook map
perspective), light matching the map, rich painterly shading.
PURE WHITE background. NO white sticker border, NO outline stroke, no text,
no ground, no cast shadow — just the painted {объект} on pure white.
```

Проверено о ракурсах и композиции:

- «seen slightly from above» обязателен — виньетка смотрится с высоты карты,
  фронтальный ракурс выглядит наклейкой;
- транспорт и животные — «facing left/right» по направлению движения на карте;
- **протяжённые объекты** (мост, поезд, причал) — требовать замкнутую
  композицию: «the whole object fits fully inside the frame with generous
  white margins, both ends visible and rounded off cleanly, nothing cut by
  frame edges» — иначе объект обрежется краем кадра и на карте будет выглядеть
  куском;
- белый фон нужен для вырезки; белые ЧАСТИ объекта (белая машина, белые стены)
  не пострадают — place_vignettes.py режет заливкой от краёв, а не по цвету;
- пояснение к виньетке в скобках модель может превратить в подпись на
  картинке — пояснения давай отдельным предложением, без скобок.
