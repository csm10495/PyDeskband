#pragma once

#include <Windows.h>
#include <thread>
#include <string>
#include <vector>
#include <map>
#include <optional>

class CDeskBand;

struct TextInfo
{
	TextInfo()
	{
		memset(this, 0, sizeof(TextInfo));
	}

	unsigned red;
	unsigned green;
	unsigned blue;

	std::string text;
	RECT rect;

	std::string toString();
};

class ControlPipe
{
public:
	ControlPipe(CDeskBand* d);
	~ControlPipe();

	DWORD msgHandler(DWORD msg);

	void paintAllTextInfos();

private:

	void asyncHandlingLoop();
	std::string processRequest(std::string message);

	HANDLE hPipe;
	std::thread asyncResponseThread;
	CDeskBand* deskband;

	std::vector<TextInfo> textInfos;
	std::map<DWORD, std::string> msgToAction;
	bool shouldStop;

	SIZE getTextSize(const std::string &text);
	std::optional<size_t> textInfoTarget;
};
#pragma once
