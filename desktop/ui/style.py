from __future__ import annotations

APP_STYLE = """
QMainWindow, QWidget { background:#f4f7f8; color:#17212b; font-family:'Microsoft YaHei','Noto Sans SC',sans-serif; font-size:12px; }
QLabel { background:transparent; }
#sidebar { background:#17212b; color:#f3f7f8; }
#brandLabel { color:#ffffff; font-weight:800; font-size:15px; line-height:1.5; padding:3px 10px 20px; }
#sidebarLabel { color:#74818b; font-size:10px; letter-spacing:1px; padding:5px 10px; }
#navButton { text-align:left; border:0; border-left:3px solid transparent; border-radius:8px; padding:10px 12px; color:#aebac2; background:transparent; font-weight:600; }
#navButton:hover { color:#ffffff; background:#25333d; }
#navButton[active="true"] { color:#ffffff; background:#293641; border-left-color:#f45d52; }
#connectionCard { border:1px solid #364651; border-radius:10px; background:#202d37; }
#connectionTitle { color:#cbd6db; font-weight:700; }
#connectionStatus { color:#8e9ba4; font-size:10px; padding:2px 0; }
#sidebarFooter { color:#778590; border-top:1px solid #2d3a44; padding-top:12px; font-size:10px; }
#eyebrow { color:#d84c43; font-weight:800; letter-spacing:1px; }
#pageTitle { color:#17212b; font-size:28px; font-weight:800; letter-spacing:-1px; padding-top:2px; }
#subtitle { color:#54616d; font-size:12px; }
QPushButton { min-height:31px; border:1px solid #d5dfe2; border-radius:7px; padding:0 11px; color:#17212b; background:#ffffff; font-weight:700; }
QPushButton:hover { border-color:#aebdc2; background:#fbfcfc; }
QPushButton#tableActionButton, QPushButton[tableAction="true"] { min-height:28px; padding:0 8px; }
#primaryButton { border:1px solid #f45d52; color:#ffffff; background:#f45d52; }
#primaryButton:hover { background:#d84c43; }
#copyButton { min-width:48px; min-height:29px; color:#54616d; background:#fbfcfc; }
#copyButton:hover { border-color:#f45d52; color:#d84c43; background:#fff7f6; }
#pulseFrame { border:1px solid #17212b; border-radius:12px; background:#17212b; min-height:104px; }
#metricCard, #metricAccent { border:0; border-left:1px solid #31404a; border-radius:0; background:#17212b; }
#metricAccent { border-left:0; border-radius:11px 0 0 11px; background:#f45d52; }
#metricLabel { color:#94a2aa; font-size:10px; }
#metricAccent #metricLabel, #metricAccent #metricValue, #metricAccent #metricNote { color:#ffffff; }
#metricValue { color:#ffffff; font-size:24px; font-weight:800; padding-top:6px; }
#metricNote { color:#87959e; font-size:10px; }
#workspaceBar { border:1px solid #dfe6e9; border-radius:9px; background:#ffffff; }
#panel { border:1px solid #dfe6e9; border-radius:12px; background:#ffffff; }
#panelTitle { color:#17212b; font-size:14px; font-weight:800; }
#panelSubtitle, #mutedLabel { color:#88939c; font-size:10px; }
#runtimeState { color:#d84c43; background:#fff1ef; border-radius:5px; padding:4px 8px; font-size:10px; font-weight:800; }
#runtimeProgress { color:#54616d; font-weight:800; min-width:32px; }
#dashboardLogView { border:1px solid #e7edef; border-radius:7px; background:#fbfcfc; color:#54616d; padding:5px 8px; }
#workflowCard { border:1px solid #dfe6e9; border-radius:9px; background:#fbfcfc; }
#workflowCard:hover { border-color:#f3aaa3; background:#fffaf9; }
#workflowTitle { color:#17212b; font-size:14px; font-weight:800; }
#workflowDescription { color:#54616d; font-size:11px; }
#workflowRoute { color:#d84c43; font-size:10px; font-weight:700; }
#workflowAction { min-height:28px; }
#sectionLabel { color:#54616d; font-size:11px; font-weight:800; padding-top:4px; }
#metricChip { color:#54616d; background:#f1f5f5; border-radius:5px; padding:4px 7px; font-size:10px; font-weight:700; }
QLineEdit, QComboBox, QTextEdit, QTextBrowser { border:1px solid #d6e0e3; border-radius:7px; background:#fbfcfc; padding:7px 9px; selection-background-color:#f7c2bc; }
QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QTextBrowser:focus { border:1px solid #f45d52; }
#commentReplyEditor { min-height:22px; max-height:28px; padding:0 7px; }
QTableWidget { border:1px solid #e6ecee; border-radius:7px; background:#ffffff; gridline-color:#edf1f2; alternate-background-color:#fbfcfc; }
QHeaderView::section { border:0; border-bottom:1px solid #edf1f2; padding:8px 7px; color:#88939c; background:#ffffff; font-size:10px; font-weight:700; }
QTableWidget::item { padding:5px; color:#54616d; }
QTableWidget::item:selected { color:#17212b; background:#fff1ef; }
QProgressBar { border:0; border-radius:4px; background:#edf2f2; height:6px; text-align:center; }
QProgressBar::chunk { border-radius:4px; background:#f45d52; }
QSplitter#analysisVerticalSplitter::handle:vertical { height:12px; background:#cbd6da; border-top:2px solid #f4f7f8; border-bottom:2px solid #f4f7f8; }
QSplitter#analysisVerticalSplitter::handle:vertical:hover { background:#f45d52; }
QSplitter#dashboardVerticalSplitter::handle:vertical { height:12px; background:#cbd6da; border-top:2px solid #f4f7f8; border-bottom:2px solid #f4f7f8; }
QSplitter#dashboardVerticalSplitter::handle:vertical:hover { background:#f45d52; }
QSplitter#collectionVerticalSplitter::handle:vertical, QSplitter#collectionOutreachSplitter::handle:vertical { height:8px; background:#edf2f2; border-top:1px solid #ffffff; border-bottom:1px solid #ffffff; }
QSplitter#collectionVerticalSplitter::handle:vertical:hover, QSplitter#collectionOutreachSplitter::handle:vertical:hover { background:#cbd6da; }
QSplitter::handle:vertical { height:10px; background:#dce5e7; border-top:2px solid #ffffff; border-bottom:2px solid #ffffff; }
QSplitter::handle:vertical:hover { background:#f45d52; }
QTabWidget::pane { border:0; }
QStatusBar { color:#6e7a81; background:#eaf0f1; border-top:1px solid #dfe6e9; }
QDialog { background:#f4f7f8; }
"""
