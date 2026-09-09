import { readFile, rename, rm, writeFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import path from "node:path";

import { chromium } from "playwright";
import { marked } from "marked";

const root = path.resolve(import.meta.dirname, "..");
const sourcePath = path.join(root, "docs", "user_guide.md");
const outputPath = path.join(root, "docs", "user_guide.pdf");
const temporaryHtml = path.join(root, "docs", ".user_guide.print.html");
const temporaryPdf = path.join(root, "docs", ".user_guide.pdf.tmp");

const markdown = await readFile(sourcePath, "utf8");
const body = await marked.parse(markdown, { gfm: true });
const baseHref = pathToFileURL(path.join(root, "docs") + path.sep).href;
const html = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <base href="${baseHref}">
  <title>Biodynamic Calendar User Guide</title>
  <style>
    @page { size: Letter; margin: 0.65in 0.62in 0.7in; }
    * { box-sizing: border-box; }
    body { color: #27313a; font: 10.2pt/1.42 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; }
    h1, h2, h3 { color: #1d5146; break-after: avoid-page; line-height: 1.2; }
    h1 { border-bottom: 3px solid #c7a636; font-size: 25pt; margin: 0 0 18pt; padding-bottom: 8pt; }
    h2 { border-bottom: 1px solid #cdbf91; font-size: 17pt; margin: 22pt 0 8pt; padding-bottom: 3pt; }
    h3 { font-size: 13pt; margin: 16pt 0 6pt; }
    p, li { orphans: 3; widows: 3; }
    a { color: #176b61; text-decoration: none; }
    code { background: #f2eee0; border-radius: 3px; font: 9pt ui-monospace, SFMono-Regular, Menlo, monospace; padding: 1px 3px; }
    img { display: block; height: auto; margin: 8pt auto; max-height: 8.15in; max-width: 100%; object-fit: contain; }
    .mobile-screenshots { width: 100%; table-layout: fixed; border-collapse: collapse; break-inside: avoid-page; }
    .mobile-screenshots th { color: #1d5146; font-size: 10pt; text-align: center; }
    .mobile-screenshots td { padding: 0 5pt; vertical-align: top; }
    blockquote { background: #f8f4e5; border-left: 3px solid #c7a636; break-inside: avoid-page; color: #46534f; margin-left: 0; padding: 7pt 10pt; }
  </style>
</head>
<body>${body}</body>
</html>`;

await writeFile(temporaryHtml, html);
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  await page.goto(pathToFileURL(temporaryHtml).href, { waitUntil: "networkidle" });
  await page.emulateMedia({ media: "print" });
  await page.pdf({
    path: temporaryPdf,
    format: "Letter",
    printBackground: true,
    displayHeaderFooter: true,
    headerTemplate: "<span></span>",
    footerTemplate: '<div style="font-size:8px;color:#68726f;text-align:center;width:100%">Biodynamic Calendar User Guide &nbsp;·&nbsp; <span class="pageNumber"></span> / <span class="totalPages"></span></div>',
    margin: { top: "0.65in", right: "0.62in", bottom: "0.7in", left: "0.62in" },
  });
  await rename(temporaryPdf, outputPath);
} finally {
  await browser.close();
  await rm(temporaryHtml, { force: true });
  await rm(temporaryPdf, { force: true });
}

console.log(`Wrote ${path.relative(root, outputPath)}`);
