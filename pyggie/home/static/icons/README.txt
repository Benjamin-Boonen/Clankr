Clank.r icons: one SVG file per name below, in this folder.
Draw on a 24x24 grid, use stroke="currentColor" (or fill="currentColor"),
no <script>. Until a file exists, a text symbol is shown instead.

Tools (shown on each tool call):
  web_search.svg    fetch_page.svg    run_python.svg    run_shell.svg
  write_file.svg    read_file.svg     create_artifact.svg  load_skill.svg
  finish.svg
Artifacts (Artifacts panel):
  artifact-html.svg    artifact-svg.svg    artifact-markdown.svg
  artifact.svg         (any other kind)
Other:
  skill.svg            (Skills panel)
  attach.svg           (attach-file button)

Model picker — family column only (model and size are text):
  family-<key>.svg
  key = leading letters of the Ollama name, lowercased.
  llama3.1:8b -> family-llama.svg,  qwen2.5-coder:7b -> family-qwen.svg,
  deepseek-r1:14b -> family-deepseek.svg, mistral:7b -> family-mistral.svg.
  A missing file falls back to a letter monogram drawn in the page.
  Drop a 24x24 currentColor SVG here to replace that family's mark.
  Do not put these on <option> elements: a native select cannot draw SVG.
