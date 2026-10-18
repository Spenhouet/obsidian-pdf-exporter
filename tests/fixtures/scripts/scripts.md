# Scripts

Text in many scripts and very long words, to check that every line stays inside its box.

## Latin Ελληνικά Русский

The quick brown fox. Γειά σου Κόσμε. Привет, мир! Combining marks: é ä ñ.

## 中文 日本語

中文段落：这是一个很长的中文句子，用来检查在没有空格的情况下是否能够在字符之间正确地换行，并且不会超出页面的边界，数据处理与结果导出流程。这是一个很长的中文句子，用来检查在没有空格的情况下是否能够在字符之间正确地换行。

日本語の段落：これはとても長い日本語の文で、空白がなくても文字と文字の間で正しく改行され、ページの端からはみ出さないことを確認します。

## العربية עברית

مرحبا بالعالم، هذا نص عربي طويل يجب أن يظهر من اليمين إلى اليسار بشكل صحيح.

שלום עולם, זה טקסט בעברית שצריך להופיע מימין לשמאל.

Mixed: Data 数据 بيانات данные δεδομένα डेटा שלום.

## हिन्दी ไทย

नमस्ते दुनिया, यह एक लंबा हिंदी वाक्य है जो पंक्ति के अंत में सही ढंग से टूटना चाहिए क्षत्रिय संस्कृत।

สวัสดีชาวโลก ภาษาไทยไม่มีการเว้นวรรคระหว่างคำจึงต้องตัดคำด้วยพจนานุกรมเพื่อให้ขึ้นบรรทัดใหม่ได้ถูกต้อง

Emoji 🚀 ✅ 👩‍💻 🌳

## Long words

Supercalifragilisticexpialidocious_and_another_very_long_identifier_without_any_spaces_that_cannot_break_anywhere_at_all_in_this_line

https://example.com/a/very/long/path/that/goes/on/and/on/without/any/spaces/to/break/at/index.html?query=parameter&another=value

`inline_code_with_a_very_long_identifier_name_that_does_not_fit_on_one_line_of_the_page_at_all`

```python
def 计算(数据, القيمة="قيمة", שם="שלום"):  # a long comment that goes past the right edge of the page for sure
    return "Привет 🚀 नमस्ते สวัสดี"
```

- First item with a long word: Donaudampfschifffahrtselektrizitätenhauptbetriebswerkbauunterbeamtengesellschaft
- 第二项：中文列表项目也应该正确换行而不超出页面右侧的边界线
- عنصر القائمة الثالث باللغة العربية
- פריט רביעי בעברית
    - Nested: ภาษาไทยในรายการซ้อน and हिन्दी सूची

## Tables

| Script | Sample | Long |
| ------ | ------ | ---- |
| 中文 | 数据处理与结果导出流程 | 这是一个很长的单元格内容需要在字符之间换行 |
| العربية | مرحبا بالعالم | نص عربي طويل داخل خلية الجدول |
| עברית | שלום עולם | טקסט ארוך בתוך תא בטבלה |
| हिन्दी | नमस्ते | क्षत्रिय संस्कृत हिंदी पाठ |
| ไทย | สวัสดี | ภาษาไทยในเซลล์ตารางที่ยาวมาก |
| Long | Pneumonoultramicroscopicsilicovolcanoconiosis_identifier | https://example.com/another/very/long/url/in/a/table/cell |

| ID | 要求 | المتطلب | דרישה | Требование | आवश्यकता | ข้อกำหนด | Status |
| -- | ---- | ------- | ----- | ---------- | -------- | -------- | ------ |
| R-1 | 导出时不需要网络连接 | التصدير بدون اتصال بالشبكة | הייצוא פועל ללא רשת | Экспорт работает без сети | निर्यात बिना नेटवर्क के | ส่งออกได้โดยไม่ต้องใช้เครือข่าย | Done |
| R-2 | 每一页显示文档版本 | كل صفحة تعرض رقم الإصدار | כל עמוד מציג גרסה | Каждая страница показывает версию | हर पृष्ठ पर संस्करण | ทุกหน้าแสดงเวอร์ชัน | Open |

## Callouts

> [!note] 注意：中文标题 and a long callout title that keeps going and going until it has to wrap
> 这是提示框的正文。

> [!warning] تحذير باللغة العربية
> نص التحذير. שלום. नमस्ते. สวัสดี.

## Footnotes and links

Footnote in Hebrew[^he] and in Chinese[^zh] and Thai.^[เชิงอรรถภาษาไทย]

Links: [[Notes 笔记]], [[Notes 笔记|别名 alias]], [[Notes 笔记#عنوان|رابط عربي]], [[Missing ページ]].

[^he]: הערת שוליים בעברית.
[^zh]: 中文脚注，内容比较长，用来检查脚注区域中的换行是否正确。

## Math

$\text{Speed} = \frac{d}{t}$, $\text{速度} = v$ and $x_{\text{max}} = 42$

$$
\sum_{i=1}^{n} x_i = \text{total}
$$

## Dataview

```dataview
TABLE name, note

WHERE name
SORT file.name ASC
```

```base
filters:
  and:
    - name
views:
  - type: table
    name: Bases
    order:
      - file.name
      - name
      - note
```
