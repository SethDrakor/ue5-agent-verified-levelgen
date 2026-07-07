using UnrealBuildTool;

public class RoomGenerator : ModuleRules
{
    public RoomGenerator(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = ModuleRules.PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(new string[] {
            "Core", "CoreUObject", "Engine",
            "AIModule",
            "HTTP",
            "JsonUtilities",
            "InputCore",
        });

        PrivateDependencyModuleNames.AddRange(new string[] {
            "UnrealEd",
            "EditorSubsystem",
            "BlueprintGraph",
            "Kismet",
            "Json",
            "Slate",
            "SlateCore",
            "EditorStyle",
            "ToolMenus",
            "WorkspaceMenuStructure",
            "PythonScriptPlugin",
            "AssetTools",
            "AssetRegistry",
        });
    }
}
