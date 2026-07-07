#pragma once
#include "Modules/ModuleInterface.h"

class FRoomGeneratorModule : public IModuleInterface
{
public:
    virtual void StartupModule() override;
    virtual void ShutdownModule() override;

private:
    TSharedRef<class SDockTab> SpawnClaudeTab(const class FSpawnTabArgs& Args);
    void RegisterMenus();
};
