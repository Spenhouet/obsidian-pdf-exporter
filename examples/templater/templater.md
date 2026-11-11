<%*
const title = await tp.system.prompt("Title of the meeting");
await tp.file.rename(title);
-%>
---
type: meeting
date: <% tp.date.now("YYYY-MM-DD") %>
---
## Agenda

1. Status of open actions
2. Next steps
<% tp.file.cursor() %>

Inline code such as `<% tp.file.title %>` is shown as written.
