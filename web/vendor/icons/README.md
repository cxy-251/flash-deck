# 播放器图标

Google Material Symbols（Rounded，400 字重），Apache License 2.0（见 LICENSE），来自 npm 包
`@material-symbols/svg-400`。只挑了播放器控件用得到的几十个，`-fill` 是实心版本。

本机 Qt（`omni/shell/icons.py`）和网页（`web/ui/icons.js`）读的都是这里同一份文件，
上色都走当前文字颜色：Qt 渲染前把 `fill` 填进 SVG，网页用 CSS mask + `currentColor`。
新增图标：从上面那个包的 `rounded/` 里拷过来即可。
