#pragma once

#include "Logger.h"

#include <atomic>
#include <filesystem>
#include <fstream>
#include <mutex>

static std::mutex logMutex;
static std::atomic<bool> loggingEnabled = false;

void log(const std::string& s)
{
	if (loggingEnabled)
	{
		logMutex.lock();
		auto logFilePath = (std::filesystem::temp_directory_path() / "pydeskband.log");
		std::ofstream outfile;
		outfile.open(logFilePath, std::ios_base::app);
		outfile << s << std::endl;
		logMutex.unlock();
	}
}

void setLoggingEnabled(bool enabled)
{
	loggingEnabled = enabled;
}
