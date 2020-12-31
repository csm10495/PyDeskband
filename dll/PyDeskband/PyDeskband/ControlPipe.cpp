#include "ControlPipe.h"
#include "DeskBand.h"
#include "Logger.h"

#include <uxtheme.h>
#include <iostream>
#include <string>
#include <sstream>
#include <vector>
#include <codecvt>
#include <locale>

#define BUFFER_SIZE (1024 * 8)
#define TRANSPORT_DELIM std::string(",")


std::vector<std::string> split(std::string s, char delim)
{
    std::vector<std::string> ret;
    std::stringstream wStringStream(s);
    while (wStringStream.good())
    {
        std::string tmp;
        std::getline(wStringStream, tmp, delim);
        ret.push_back(tmp);
    }
    return ret;
}

std::wstring to_wstring(std::string str)
{
    using convert_t = std::codecvt_utf8<wchar_t>;
    std::wstring_convert<convert_t, wchar_t> strconverter;
    return strconverter.from_bytes(str);
}

ControlPipe::ControlPipe(CDeskBand* d)
{
    hPipe = CreateNamedPipe(TEXT("\\\\.\\pipe\\PyDeskbandControlPipe"),
        PIPE_ACCESS_DUPLEX,
        PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
        1,
        BUFFER_SIZE,
        BUFFER_SIZE,
        NMPWAIT_USE_DEFAULT_WAIT,
        NULL);

    deskband = d;
    shouldStop = false;

    this->asyncResponseThread = std::thread(&ControlPipe::asyncHandlingLoop, this);
}

ControlPipe::~ControlPipe()
{
    CloseHandle(hPipe);
    hPipe = INVALID_HANDLE_VALUE;
}

DWORD ControlPipe::msgHandler(DWORD msg)
{
    if (msgToAction.find(msg) != msgToAction.end())
    {
        return system(msgToAction[msg].c_str());
    }
    return 0;
}

void ControlPipe::paintAllTextInfos()
{
    auto m_hwnd = deskband->m_hwnd;
    PAINTSTRUCT ps;
    HDC hdc = BeginPaint(m_hwnd, &ps);
    RECT clientRectangle;
    GetClientRect(m_hwnd, &clientRectangle);
    HDC hdcPaint = NULL;
    HPAINTBUFFER hBufferedPaint = BeginBufferedPaint(hdc, &clientRectangle, BPBF_TOPDOWNDIB, NULL, &hdcPaint);
    DrawThemeParentBackground(m_hwnd, hdcPaint, &clientRectangle);

    HTHEME hTheme = OpenThemeData(NULL, L"BUTTON");

    for (auto& textInfo : textInfos)
    {
        log("Painting: " + textInfo.toString());

        if (hdc)
        {
            if (deskband->m_fCompositionEnabled)
            {
                if (hTheme)
                {

                    SIZE textSize = getTextSize(textInfo.text);

                    DTTOPTS dttOpts = { sizeof(dttOpts) };
                    dttOpts.dwFlags = DTT_COMPOSITED | DTT_TEXTCOLOR | DTT_GLOWSIZE;
                    dttOpts.crText = RGB(textInfo.red, textInfo.green, textInfo.blue);
                    dttOpts.iGlowSize = 10;

                    // textInfo.rect.left = (RECTWIDTH(clientRectangle) - textSize.cx) / 2;
                    // textInfo.rect.top = (RECTHEIGHT(clientRectangle) - textSize.cy) / 2;
                    textInfo.rect.right = textInfo.rect.left + textSize.cx;
                    textInfo.rect.bottom = textInfo.rect.top + textSize.cy;

                    auto w = to_wstring(textInfo.text);
                    DrawThemeTextEx(hTheme, hdcPaint, 0, 0, w.c_str(), -1, 0, &textInfo.rect, &dttOpts);
                }
            }
            else
            {
                abort();
                /*
                auto w = to_wstring(textInfo.text);

                SetBkColor(hdc, RGB(textInfo.red, textInfo.green, textInfo.blue));
                GetTextExtentPointA(hdc, textInfo.text.c_str(), (int)textInfo.text.size(), &size);
                TextOutW(hdc,
                    (RECTWIDTH(rc) - size.cx) / 2,
                    (RECTHEIGHT(rc) - size.cy) / 2,
                    w.c_str(),
                    (int)w.size());
                */
            }
        }
    }

    CloseThemeData(hTheme);
    EndBufferedPaint(hBufferedPaint, TRUE);
    EndPaint(m_hwnd, &ps);
}

void ControlPipe::asyncHandlingLoop()
{
    log("Starting loop");

    char buffer[BUFFER_SIZE] = { 0 };
    DWORD dwRead;

    while (hPipe != INVALID_HANDLE_VALUE)
    {
        // will wait for a connection
        if (ConnectNamedPipe(hPipe, NULL) != FALSE)
        {
            while (ReadFile(hPipe, buffer, sizeof(buffer) - 1, &dwRead, NULL) != FALSE)
            {
                /* add terminating zero */
                buffer[dwRead] = '\0';
                std::string sBuffer((char*)buffer);
                log("Request: " + sBuffer);

                std::string response = processRequest(sBuffer);
                log("Response: " + response);

                if (response.size())
                {
                    bool out = WriteFile(hPipe,
                        response.data(),
                        (DWORD)(response.size()),
                        &dwRead,
                        NULL);
                }

                if (shouldStop)
                {
                    log("Detected stop condition");
                    CloseHandle(hPipe);
                    hPipe = INVALID_HANDLE_VALUE;
                    break;
                }
            }
        }
        DisconnectNamedPipe(hPipe);
    }

    log("Exited loop");
}

std::string ControlPipe::processRequest(std::string message)
{
    std::string ret = "BadCommand";
    auto lineSplit = split(message, TRANSPORT_DELIM[0]);
    auto textInfo = getTextInfoTarget();

    #define ENSURE_TEXT_INFO_OK() if (textInfo == NULL) { return "OutOfBoundsTextInfoTarget\n";}

    if (lineSplit.size())
    {
        if (lineSplit[0] == "GET")
        {
            if (lineSplit[1] == "WIDTH")
            {
                RECT rc;
                GetClientRect(deskband->m_hwnd, &rc);
                ret = std::to_string(rc.right - rc.left);
            }
            else if (lineSplit[1] == "HEIGHT")
            {
                RECT rc;
                GetClientRect(deskband->m_hwnd, &rc);
                ret = std::to_string(rc.bottom - rc.top);
            }
            else if (lineSplit[1] == "TEXTSIZE")
            {
                auto size = getTextSize(lineSplit[2]);
                ret = std::to_string(size.cx) + TRANSPORT_DELIM + std::to_string(size.cy);
            }
            else if (lineSplit[1] == "TEXTINFOCOUNT")
            {
                ret = std::to_string(textInfos.size());
            }
            else if (lineSplit[1] == "TEXTINFO_TARGET")
            {
                if (textInfoTarget)
                {
                    ret = std::to_string(*textInfoTarget);
                }
                else
                {
                    ret = "None";
                }
            }
            else if (lineSplit[1] == "RGB")
            {
                ENSURE_TEXT_INFO_OK();
                ret = std::to_string(textInfo->red) + TRANSPORT_DELIM + std::to_string(textInfo->green) + TRANSPORT_DELIM + std::to_string(textInfo->blue);
            }
            else if (lineSplit[1] == "TEXT")
            {
                ENSURE_TEXT_INFO_OK();
                ret = textInfo->text;
            }
            else if (lineSplit[1] == "XY")
            {
                ENSURE_TEXT_INFO_OK();
                ret = std::to_string(textInfo->rect.left) + TRANSPORT_DELIM + std::to_string(textInfo->rect.top);
            }
        }
        else if (lineSplit[0] == "SET")
        {
            if (lineSplit[1] == "RGB")
            {
                ENSURE_TEXT_INFO_OK();
                textInfo->red = std::stoi(lineSplit[2]);
                textInfo->green = std::stoi(lineSplit[3]);
                textInfo->blue = std::stoi(lineSplit[4]);
                ret = "OK";
            }
            else if (lineSplit[1] == "TEXT")
            {
                ENSURE_TEXT_INFO_OK();
                textInfo->text = std::string(lineSplit[2]);
                ret = "OK";
            }
            else if (lineSplit[1] == "XY")
            {
                ENSURE_TEXT_INFO_OK();

                // xy from top left
                textInfo->rect.left = std::stol(lineSplit[2]);
                textInfo->rect.top = std::stol(lineSplit[3]);
                ret = "OK";
            }
            else if (lineSplit[1] == "WIN_MSG")
            {
                // set a (not already handled) Windows Message control to call something
                auto msg = std::stoi(lineSplit[2]);
                if (lineSplit.size() < 4)
                {
                    if (msgToAction.find(msg) != msgToAction.end())
                    {
                        msgToAction.erase(msg);
                        ret = "OK";
                    }
                    else
                    {
                        ret = "MSG_NOT_FOUND";
                    }
                }
                else
                {
                    auto sysCall = std::string(lineSplit[3]);
                    msgToAction[msg] = sysCall;
                    ret = "OK";
                }
            }
            else if (lineSplit[1] == "TEXTINFO_TARGET")
            {
                if (lineSplit.size() == 3)
                {
                    textInfoTarget = (size_t)std::stoull(lineSplit[2]);
                    log("Set textInfoTarget to: " + std::to_string(*textInfoTarget));
                }
                else
                {
                    textInfoTarget.reset();
                    log("Set textInfoTarget to: <reset>");
                }
                ret = "OK";
            }
            else if (lineSplit[1] == "LOGGING_ENABLED")
            {
                setLoggingEnabled((bool)std::stoi(lineSplit[2]));
                ret = "OK";
            }
        }
        else if (lineSplit[0] == "NEW_TEXTINFO")
        {
            textInfos.push_back(TextInfo());
            ret = "OK";
        }
        else if (lineSplit[0] == "PAINT")
        {
            InvalidateRect(deskband->m_hwnd, NULL, true);
            ret = "OK";
        }
        else if (lineSplit[0] == "CLEAR")
        {
            textInfos.clear();
            InvalidateRect(deskband->m_hwnd, NULL, true);
            ret = "OK";
        }
        else if (lineSplit[0] == "STOP")
        {
            shouldStop = true;
            ret = "OK";
        }
        else if (lineSplit[0] == "SENDMESSAGE")
        {
            SendMessage(deskband->m_hwnd, std::stoi(lineSplit[1]), 0, 0);
            ret = "OK";
        }
    }

    return ret + '\n';
}

SIZE ControlPipe::getTextSize(const std::string& text)
{
    HDC dc = GetDC(deskband->m_hwnd);
    SIZE sz = { 0 };
    GetTextExtentPoint32A(dc, text.c_str(), (int)text.size(), &sz);
    ReleaseDC(deskband->m_hwnd, dc);
    return sz;
}

TextInfo* ControlPipe::getTextInfoTarget()
{
    if (textInfos.size() == 0)
    {
        textInfos.push_back(TextInfo());
    }

    // get a ref to the last text info
    auto textInfo = &textInfos[textInfos.size() - 1];

    // swap that ref if textInfoTarget is set.
    if (textInfoTarget)
    {
        if (*textInfoTarget < textInfos.size())
        {
            textInfo = &textInfos[*textInfoTarget];
        }
        else
        {
            log("Out of bounds text info target: " + std::to_string(*textInfoTarget));
            textInfo = NULL;
        }
    }

    return textInfo;
}

std::string TextInfo::toString()
{
    std::string retString = "";
    retString += "TextInfo\n";
    retString += "  Red:      " + std::to_string(red) + "\n";
    retString += "  Green:    " + std::to_string(green) + "\n";
    retString += "  Blue:     " + std::to_string(blue) + "\n";
    retString += "  Rect:\n";
    retString += "    Left:   " + std::to_string(rect.left) + "\n";
    retString += "    Top:    " + std::to_string(rect.top) + "\n";
    retString += "    Right:  " + std::to_string(rect.right) + "\n";
    retString += "    Bottom: " + std::to_string(rect.bottom) + "\n";
    retString += "  Text:     " + text + "\n";
    return retString;
}
