#include "ControlPipe.h"
#include "DeskBand.h"
#include "Logger.h"

#include <uxtheme.h>
#include <exception>
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

class TextInfoNullException : public std::exception
{
    using std::exception::exception;
};

TextInfo* verifyTextInfo(TextInfo* textInfo)
{
    if (textInfo == NULL)
    { 
        throw TextInfoNullException("TextInfo was NULL");
    }
    return textInfo;
}

std::string ControlPipe::processRequest(std::string message)
{
    // std::string ret = "BadCommand";
    auto lineSplit = split(message, TRANSPORT_DELIM[0]);

    // Do not use __textInfo directly... it may be NULL. Use GET_TEXT_INFO, which will throw if NULL.
    auto __textInfo = getTextInfoTarget();
    #define GET_TEXT_INFO() verifyTextInfo(__textInfo)

    Response response;
    
    try
    {
        if (lineSplit.size())
        {
            if (lineSplit[0] == "GET")
            {
                if (lineSplit[1] == "WIDTH")
                {
                    RECT rc;
                    GetClientRect(deskband->m_hwnd, &rc);
                    response.addField(std::to_string(rc.right - rc.left));
                }
                else if (lineSplit[1] == "HEIGHT")
                {
                    RECT rc;
                    GetClientRect(deskband->m_hwnd, &rc);
                    response.addField(std::to_string(rc.bottom - rc.top));
                }
                else if (lineSplit[1] == "TEXTSIZE")
                {
                    auto size = getTextSize(lineSplit[2]);
                    response.addField(std::to_string(size.cx));
                    response.addField(std::to_string(size.cy));
                }
                else if (lineSplit[1] == "TEXTINFOCOUNT")
                {
                    response.addField(std::to_string(textInfos.size()));
                }
                else if (lineSplit[1] == "TEXTINFO_TARGET")
                {
                    if (textInfoTarget)
                    {
                        response.addField(std::to_string(*textInfoTarget));
                    }
                    else
                    {
                        response.addField("None");
                    }
                }
                else if (lineSplit[1] == "RGB")
                {
                    auto textInfo = GET_TEXT_INFO();
                    response.addField(std::to_string(textInfo->red));
                    response.addField(std::to_string(textInfo->green));
                    response.addField(std::to_string(textInfo->blue));
                }
                else if (lineSplit[1] == "TEXT")
                {
                    auto textInfo = GET_TEXT_INFO();
                    response.addField(textInfo->text);
                }
                else if (lineSplit[1] == "XY")
                {
                    auto textInfo = GET_TEXT_INFO();
                    response.addField(std::to_string(textInfo->rect.left));
                    response.addField(std::to_string(textInfo->rect.top));
                }
                else if (lineSplit[1] == "TRANSPORT_VERSION")
                {
                    auto textInfo = GET_TEXT_INFO();
                    response.addField("1");
                }
            }
            else if (lineSplit[0] == "SET")
            {
                if (lineSplit[1] == "RGB")
                {
                    auto textInfo = GET_TEXT_INFO();
                    textInfo->red = std::stoi(lineSplit[2]);
                    textInfo->green = std::stoi(lineSplit[3]);
                    textInfo->blue = std::stoi(lineSplit[4]);
                    response.setOk();
                }
                else if (lineSplit[1] == "TEXT")
                {
                    auto textInfo = GET_TEXT_INFO();
                    textInfo->text = std::string(lineSplit[2]);
                    response.setOk();
                }
                else if (lineSplit[1] == "XY")
                {
                    auto textInfo = GET_TEXT_INFO();

                    // xy from top left
                    textInfo->rect.left = std::stol(lineSplit[2]);
                    textInfo->rect.top = std::stol(lineSplit[3]);
                    response.setOk();
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
                            response.setOk();
                        }
                        else
                        {
                            response.setStatus("MSG_NOT_FOUND");
                        }
                    }
                    else
                    {
                        auto sysCall = std::string(lineSplit[3]);
                        msgToAction[msg] = sysCall;
                        response.setOk();
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
                    response.setOk();
                }
                else if (lineSplit[1] == "LOGGING_ENABLED")
                {
                    setLoggingEnabled((bool)std::stoi(lineSplit[2]));
                    response.setOk();
                }
            }
            else if (lineSplit[0] == "NEW_TEXTINFO")
            {
                textInfos.push_back(TextInfo());
                response.setOk();
            }
            else if (lineSplit[0] == "PAINT")
            {
                InvalidateRect(deskband->m_hwnd, NULL, true);
                response.setOk();
            }
            else if (lineSplit[0] == "CLEAR")
            {
                textInfos.clear();
                InvalidateRect(deskband->m_hwnd, NULL, true);
                response.setOk();
            }
            else if (lineSplit[0] == "STOP")
            {
                shouldStop = true;
                response.setOk();
            }
            else if (lineSplit[0] == "SENDMESSAGE")
            {
                SendMessage(deskband->m_hwnd, std::stoi(lineSplit[1]), 0, 0);
                response.setOk();;
            }
        }
    }
    catch (TextInfoNullException)
    {
        response.setStatus("TextInfoTargetInvalid");
    }

    return response.toString();
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

Response::Response()
{
    status = "BadCommand";
}

void Response::addField(std::string field)
{
    fields.push_back(field);
    status = "OK";
}

void Response::setStatus(std::string status)
{
    this->status = status;
}

void Response::setOk()
{
    status = "OK";
}

std::string Response::toString()
{
    std::string ret = status + TRANSPORT_DELIM;
    for (auto& field : fields)
    {
        ret += field + TRANSPORT_DELIM;
    }

    return ret + "\n";
}
