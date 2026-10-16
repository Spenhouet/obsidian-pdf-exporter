```dataviewjs
const projects = dv.pages("#project").sort(p => p.due, "asc");
dv.header(4, "Projects by owner");
for (const group of projects.groupBy(p => p.owner)) {
  dv.paragraph(`**${group.key}**: ${group.rows.file.name.join(", ")}`);
}
dv.table(["Project", "Due", "Done"],
  projects.map(p => [p.file.link, p.due, p.status === "done" ? "yes" : "no"]));
const open = dv.pages('"_notes/Journal"').file.tasks.where(t => !t.completed);
dv.paragraph(`Open tasks: ${open.length}`);
```

Open projects: `$= dv.pages("#project").where(p => p.status != "done").length`
