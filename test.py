from pywinauto import Desktop

windows = Desktop(backend="uia").windows()
for w in windows:
    print(w.window_text())