/* SaxoPortfolio.exe – kleiner Windows-Starter (ohne Konsolenfenster).
 * Sucht das installierte Python und startet app\launcher.pyw mit pythonw.exe.
 * Build: python -m ziglang cc -target x86_64-windows-gnu -O2 -municode -mwindows launcher.c icon.rc -o SaxoPortfolio.exe
 */
#include <windows.h>
#include <wchar.h>
#include <stdlib.h>

static const wchar_t *TITLE = L"Saxo Portfolio";

static int exists(const wchar_t *p) { return GetFileAttributesW(p) != INVALID_FILE_ATTRIBUTES; }

/* Höchste Version in <root>\Python3XX\pythonw.exe */
static int find_in(const wchar_t *root, wchar_t *out) {
    wchar_t pattern[MAX_PATH];
    swprintf(pattern, MAX_PATH, L"%ls\\Python3*", root);
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pattern, &fd);
    if (h == INVALID_HANDLE_VALUE) return 0;
    int best = -1;
    do {
        if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) continue;
        int minor = _wtoi(fd.cFileName + 7); /* "Python313" -> 13 */
        wchar_t cand[MAX_PATH];
        swprintf(cand, MAX_PATH, L"%ls\\%ls\\pythonw.exe", root, fd.cFileName);
        if (minor >= 10 && minor > best && exists(cand)) { best = minor; wcscpy(out, cand); }
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    return best >= 0;
}

static int find_python(wchar_t *out, int *is_py_launcher) {
    wchar_t root[MAX_PATH], tmp[MAX_PATH];
    *is_py_launcher = 0;
    if (GetEnvironmentVariableW(L"LOCALAPPDATA", tmp, MAX_PATH)) {
        swprintf(root, MAX_PATH, L"%ls\\Programs\\Python", tmp);
        if (find_in(root, out)) return 1;
    }
    if (GetEnvironmentVariableW(L"ProgramFiles", tmp, MAX_PATH) && find_in(tmp, out)) return 1;
    if (SearchPathW(NULL, L"pyw.exe", NULL, MAX_PATH, out, NULL)) { *is_py_launcher = 1; return 1; }
    if (SearchPathW(NULL, L"pythonw.exe", NULL, MAX_PATH, out, NULL) && !wcsstr(out, L"WindowsApps")) return 1;
    return 0;
}

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE hPrev, PWSTR cmd, int show) {
    (void)hInst; (void)hPrev; (void)cmd; (void)show;
    wchar_t base[MAX_PATH];
    GetModuleFileNameW(NULL, base, MAX_PATH);
    wchar_t *slash = wcsrchr(base, L'\\');
    if (slash) *slash = 0;

    wchar_t script[MAX_PATH];
    swprintf(script, MAX_PATH, L"%ls\\app\\launcher.pyw", base);
    if (!exists(script)) {
        MessageBoxW(NULL, L"Der Ordner \"app\" fehlt neben SaxoPortfolio.exe.\n\n"
                          L"Bitte den ganzen Ordner \"SaxoPortfolio\" aus der ZIP-Datei entpacken.", TITLE, MB_ICONERROR);
        return 1;
    }
    wchar_t py[MAX_PATH] = {0};
    int is_py = 0;
    if (!find_python(py, &is_py)) {
        MessageBoxW(NULL, L"Python wurde nicht gefunden.\n\nBitte Python 3.11 oder neuer von python.org installieren "
                          L"(Haken bei \"Add python.exe to PATH\").", TITLE, MB_ICONERROR);
        return 1;
    }
    wchar_t cmdline[4 * MAX_PATH];
    swprintf(cmdline, 4 * MAX_PATH, L"\"%ls\" %ls\"%ls\" \"%ls\"", py, is_py ? L"-3 " : L"", script, base);

    STARTUPINFOW si = {0};
    PROCESS_INFORMATION pi = {0};
    si.cb = sizeof(si);
    if (!CreateProcessW(NULL, cmdline, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, base, &si, &pi)) {
        wchar_t err[512];
        swprintf(err, 512, L"Start fehlgeschlagen (Fehler %lu).\n%ls", GetLastError(), cmdline);
        MessageBoxW(NULL, err, TITLE, MB_ICONERROR);
        return 1;
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
