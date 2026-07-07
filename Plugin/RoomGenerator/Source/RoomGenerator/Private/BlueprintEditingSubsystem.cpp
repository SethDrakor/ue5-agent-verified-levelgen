#include "BlueprintEditingSubsystem.h"
#include "Engine/Blueprint.h"
#include "EdGraph/EdGraph.h"
#include "EdGraph/EdGraphNode.h"
#include "EdGraph/EdGraphPin.h"
#include "EdGraph/EdGraphSchema.h"
#include "Kismet2/BlueprintEditorUtils.h"
#include "K2Node_CallFunction.h"
#include "K2Node_DynamicCast.h"
#include "K2Node_MacroInstance.h"
#include "K2Node_IfThenElse.h"
#include "K2Node_VariableGet.h"
#include "K2Node_VariableSet.h"
#include "K2Node_ExecutionSequence.h"
#include "K2Node_CustomEvent.h"
#include "K2Node_Event.h"
#include "EdGraphSchema_K2.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
// MoveFolder
#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetToolsModule.h"
#include "IAssetTools.h"
#include "AssetRegistry/AssetData.h"

// ── Helpers privés ──────────────────────────────────────────────────────────

UEdGraph* UBlueprintEditingSubsystem::FindGraphInternal(UBlueprint* BP, const FName& GraphFName)
{
    for (UEdGraph* G : BP->UbergraphPages)
        if (G && G->GetFName() == GraphFName) return G;
    for (UEdGraph* G : BP->FunctionGraphs)
        if (G && G->GetFName() == GraphFName) return G;
    for (UEdGraph* G : BP->MacroGraphs)
        if (G && G->GetFName() == GraphFName) return G;
    return nullptr;
}

// Direction: -1=any, 0=EGPD_Output, 1=EGPD_Input
// NOTE: UE5 enum values are EGPD_Input=0, EGPD_Output=1 — opposite of this function's parameter convention.
// We map explicitly: param 0 → EGPD_Output, param 1 → EGPD_Input.
UEdGraphPin* UBlueprintEditingSubsystem::FindPinByName(UEdGraphNode* Node, const FString& PinName, int32 Direction)
{
    if (!Node) return nullptr;

    // Map parameter convention to actual UE enum
    auto DirOk = [Direction](const UEdGraphPin* Pin) -> bool
    {
        if (Direction < 0) return true;
        EEdGraphPinDirection Expected = (Direction == 0) ? EGPD_Output : EGPD_Input;
        return Pin->Direction == Expected;
    };

    // Step 1: Exact name match with correct direction
    for (UEdGraphPin* Pin : Node->Pins)
    {
        if (!Pin) continue;
        if (DirOk(Pin) && Pin->PinName.ToString().Equals(PinName, ESearchCase::IgnoreCase))
            return Pin;
    }

    // Step 2: "execute"/"exec"/"" alias → first INPUT exec pin (Direction==1 = input search)
    if (Direction != 0 && (PinName.Equals(TEXT("execute"), ESearchCase::IgnoreCase) || PinName.Equals(TEXT("exec"), ESearchCase::IgnoreCase) || PinName.IsEmpty()))
    {
        for (UEdGraphPin* Pin : Node->Pins)
            if (Pin && Pin->Direction == EGPD_Input && Pin->PinType.PinCategory == UEdGraphSchema_K2::PC_Exec)
                return Pin;
    }

    // Step 3: "then" alias → first OUTPUT exec pin (Direction==0 = output search)
    if (Direction != 1 && PinName.Equals(TEXT("then"), ESearchCase::IgnoreCase))
    {
        for (UEdGraphPin* Pin : Node->Pins)
            if (Pin && Pin->Direction == EGPD_Output && Pin->PinType.PinCategory == UEdGraphSchema_K2::PC_Exec)
                return Pin;
    }

    // Step 4: Partial name match with correct direction
    for (UEdGraphPin* Pin : Node->Pins)
    {
        if (!Pin) continue;
        if (DirOk(Pin) && Pin->PinName.ToString().Contains(PinName, ESearchCase::IgnoreCase))
            return Pin;
    }
    return nullptr;
}

// ── Méthodes publiques ───────────────────────────────────────────────────────

UEdGraph* UBlueprintEditingSubsystem::FindGraph(UBlueprint* Blueprint, const FString& GraphName)
{
    if (!Blueprint) return nullptr;
    return FindGraphInternal(Blueprint, FName(*GraphName));
}

UClass* UBlueprintEditingSubsystem::ResolveClass(const FString& ClassPath)
{
    UClass* Found = FindObject<UClass>(nullptr, *ClassPath);
    if (Found) return Found;
    Found = LoadClass<UObject>(nullptr, *ClassPath);
    if (Found) return Found;
    FString WithC = ClassPath + TEXT("_C");
    return LoadClass<UObject>(nullptr, *WithC);
}

UEdGraphNode* UBlueprintEditingSubsystem::AddFunctionCallNode(
    UBlueprint* Blueprint, const FString& GraphName,
    const FString& FunctionName, const FString& ClassName,
    int32 NodeX, int32 NodeY)
{
    if (!Blueprint) return nullptr;
    UEdGraph* Graph = FindGraphInternal(Blueprint, FName(*GraphName));
    if (!Graph) return nullptr;
    UClass* OwnerClass = ResolveClass(ClassName);
    if (!OwnerClass) return nullptr;
    UFunction* Function = OwnerClass->FindFunctionByName(*FunctionName, EIncludeSuperFlag::IncludeSuper);
    if (!Function) return nullptr;
    UK2Node_CallFunction* Node = NewObject<UK2Node_CallFunction>(Graph);
    Node->SetFromFunction(Function);
    Node->NodePosX = NodeX;
    Node->NodePosY = NodeY;
    Graph->AddNode(Node, true, false);
    Node->AllocateDefaultPins();
    FBlueprintEditorUtils::MarkBlueprintAsModified(Blueprint);
    return Node;
}

UEdGraphNode* UBlueprintEditingSubsystem::AddCastNode(
    UBlueprint* Blueprint, const FString& GraphName,
    const FString& TargetClassName, int32 NodeX, int32 NodeY)
{
    if (!Blueprint) return nullptr;
    UEdGraph* Graph = FindGraphInternal(Blueprint, FName(*GraphName));
    if (!Graph) return nullptr;
    UClass* TargetClass = ResolveClass(TargetClassName);
    if (!TargetClass) return nullptr;
    UK2Node_DynamicCast* CastNode = NewObject<UK2Node_DynamicCast>(Graph);
    CastNode->TargetType = TargetClass;
    CastNode->NodePosX = NodeX;
    CastNode->NodePosY = NodeY;
    CastNode->SetPurity(false);
    Graph->AddNode(CastNode, true, false);
    CastNode->AllocateDefaultPins();
    FBlueprintEditorUtils::MarkBlueprintAsModified(Blueprint);
    return CastNode;
}

UEdGraphNode* UBlueprintEditingSubsystem::AddMacroNode(
    UBlueprint* Blueprint, const FString& GraphName,
    const FString& MacroName, int32 NodeX, int32 NodeY)
{
    if (!Blueprint) return nullptr;
    UEdGraph* Graph = FindGraphInternal(Blueprint, FName(*GraphName));
    if (!Graph) return nullptr;
    static const FString MacroLibPath = TEXT("/Engine/EditorBlueprintResources/StandardMacros.StandardMacros");
    UBlueprint* MacroLib = LoadObject<UBlueprint>(nullptr, *MacroLibPath);
    if (!MacroLib) return nullptr;
    UEdGraph* MacroGraph = nullptr;
    for (UEdGraph* MG : MacroLib->MacroGraphs)
        if (MG && MG->GetName().Equals(MacroName, ESearchCase::IgnoreCase))
        { MacroGraph = MG; break; }
    if (!MacroGraph) return nullptr;
    UK2Node_MacroInstance* MacroNode = NewObject<UK2Node_MacroInstance>(Graph);
    MacroNode->SetMacroGraph(MacroGraph);
    MacroNode->NodePosX = NodeX;
    MacroNode->NodePosY = NodeY;
    Graph->AddNode(MacroNode, true, false);
    MacroNode->AllocateDefaultPins();
    FBlueprintEditorUtils::MarkBlueprintAsModified(Blueprint);
    return MacroNode;
}

UEdGraphNode* UBlueprintEditingSubsystem::AddForEachLoopNode(
    UBlueprint* Blueprint, const FString& GraphName, int32 NodeX, int32 NodeY)
{
    return AddMacroNode(Blueprint, GraphName, TEXT("ForEachLoop"), NodeX, NodeY);
}

// ── BatchWireGraph ───────────────────────────────────────────────────────────

FString UBlueprintEditingSubsystem::BatchWireGraph(
    UBlueprint* Blueprint, const FString& GraphName, const FString& GraphJson)
{
    if (!Blueprint) return TEXT("Error: Blueprint null");
    UEdGraph* Graph = FindGraphInternal(Blueprint, FName(*GraphName));
    if (!Graph) return FString::Printf(TEXT("Error: Graph not found: %s"), *GraphName);

    TSharedPtr<FJsonObject> Root;
    TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(GraphJson);
    if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
        return TEXT("Error: JSON parse failed");

    TMap<FString, UEdGraphNode*> NodeMap;
    int32 NodesCreated = 0, ConnsCreated = 0;

    const TArray<TSharedPtr<FJsonValue>>* NodesArr;
    if (Root->TryGetArrayField(TEXT("nodes"), NodesArr))
    {
        for (const auto& V : *NodesArr)
        {
            const TSharedPtr<FJsonObject> N = V->AsObject();
            if (!N.IsValid()) continue;
            FString Id   = N->GetStringField(TEXT("id"));
            FString Type = N->GetStringField(TEXT("type"));
            int32 X = N->HasField(TEXT("x")) ? (int32)N->GetNumberField(TEXT("x")) : 0;
            int32 Y = N->HasField(TEXT("y")) ? (int32)N->GetNumberField(TEXT("y")) : 0;
            UEdGraphNode* Created = nullptr;

            if (Type == TEXT("event"))
            {
                FString EvName = N->GetStringField(TEXT("name"));
                // 1. Chercher un event node existant (par FunctionName ou Title)
                for (UEdGraphNode* GN : Graph->Nodes)
                {
                    if (UK2Node_Event* Ev = Cast<UK2Node_Event>(GN))
                    {
                        FString FnName = Ev->EventReference.GetMemberName().ToString();
                        FString Title  = Ev->GetNodeTitle(ENodeTitleType::ListView).ToString();
                        if (FnName.Equals(EvName, ESearchCase::IgnoreCase) || Title.Contains(EvName, ESearchCase::IgnoreCase))
                        { Created = Ev; break; }
                    }
                    if (!Created) if (UK2Node_CustomEvent* CE = Cast<UK2Node_CustomEvent>(GN))
                        if (CE->CustomFunctionName.ToString().Equals(EvName, ESearchCase::IgnoreCase))
                        { Created = CE; break; }
                }
                // 2. Si non trouvé : créer l'event node en le résolvant dans la hiérarchie de classes
                if (!Created)
                {
                    // Aliases communs (nom court → nom UE interne)
                    FString FuncName = EvName;
                    if      (EvName.Equals(TEXT("BeginPlay"),          ESearchCase::IgnoreCase)) FuncName = TEXT("ReceiveBeginPlay");
                    else if (EvName.Equals(TEXT("Tick"),               ESearchCase::IgnoreCase)) FuncName = TEXT("ReceiveTick");
                    else if (EvName.Equals(TEXT("EndPlay"),            ESearchCase::IgnoreCase)) FuncName = TEXT("ReceiveEndPlay");
                    else if (EvName.Equals(TEXT("ActorBeginOverlap"),  ESearchCase::IgnoreCase)) FuncName = TEXT("ReceiveActorBeginOverlap");
                    else if (EvName.Equals(TEXT("ActorEndOverlap"),    ESearchCase::IgnoreCase)) FuncName = TEXT("ReceiveActorEndOverlap");
                    else if (EvName.Equals(TEXT("PossessedBy"),        ESearchCase::IgnoreCase)) FuncName = TEXT("ReceivePossessed");

                    UFunction* EventFunc = nullptr;
                    if (Blueprint->ParentClass)
                    {
                        EventFunc = Blueprint->ParentClass->FindFunctionByName(*FuncName);
                        if (!EventFunc) EventFunc = Blueprint->ParentClass->FindFunctionByName(*EvName);
                    }

                    if (EventFunc)
                    {
                        UK2Node_Event* NewEv = NewObject<UK2Node_Event>(Graph);
                        NewEv->EventReference.SetFromField<UFunction>(EventFunc, false);
                        NewEv->bOverrideFunction = true;
                        NewEv->NodePosX = X;
                        NewEv->NodePosY = Y;
                        Graph->AddNode(NewEv, true, false);
                        NewEv->AllocateDefaultPins();
                        NewEv->PostPlacedNewNode();
                        Created = NewEv;
                    }
                }
                if (!Created) return FString::Printf(TEXT("Error: Event not found: %s"), *EvName);
            }
            else if (Type == TEXT("custom_event"))
            {
                FString EvName = N->GetStringField(TEXT("name"));
                UK2Node_CustomEvent* CE = NewObject<UK2Node_CustomEvent>(Graph);
                CE->CustomFunctionName = FName(*EvName);
                CE->NodePosX = X; CE->NodePosY = Y;
                CE->bInternalEvent = false;
                Graph->AddNode(CE, true, false);
                CE->AllocateDefaultPins();
                Created = CE;
            }
            else if (Type == TEXT("function"))
            {
                FString Fn  = N->GetStringField(TEXT("fn"));
                FString Cls = N->HasField(TEXT("cls")) ? N->GetStringField(TEXT("cls")) : TEXT("");
                Created = AddFunctionCallNode(Blueprint, GraphName, Fn, Cls, X, Y);
                if (!Created) return FString::Printf(TEXT("Error: Function not found: %s on %s"), *Fn, *Cls);
            }
            else if (Type == TEXT("cast"))
            {
                FString Cls = N->GetStringField(TEXT("cls"));
                Created = AddCastNode(Blueprint, GraphName, Cls, X, Y);
                if (!Created) return FString::Printf(TEXT("Error: Cast class not found: %s"), *Cls);
            }
            else if (Type == TEXT("branch"))
            {
                UK2Node_IfThenElse* BN = NewObject<UK2Node_IfThenElse>(Graph);
                BN->NodePosX = X; BN->NodePosY = Y;
                Graph->AddNode(BN, true, false);
                BN->AllocateDefaultPins();
                Created = BN;
            }
            else if (Type == TEXT("macro"))
            {
                FString MName = N->GetStringField(TEXT("name"));
                Created = AddMacroNode(Blueprint, GraphName, MName, X, Y);
                if (!Created) return FString::Printf(TEXT("Error: Macro not found: %s"), *MName);
            }
            else if (Type == TEXT("var_get"))
            {
                FString Var = N->GetStringField(TEXT("var"));
                UK2Node_VariableGet* VG = NewObject<UK2Node_VariableGet>(Graph);
                VG->VariableReference.SetSelfMember(FName(*Var));
                VG->NodePosX = X; VG->NodePosY = Y;
                Graph->AddNode(VG, true, false);
                VG->AllocateDefaultPins();
                Created = VG;
            }
            else if (Type == TEXT("var_set"))
            {
                FString Var = N->GetStringField(TEXT("var"));
                UK2Node_VariableSet* VS = NewObject<UK2Node_VariableSet>(Graph);
                VS->VariableReference.SetSelfMember(FName(*Var));
                VS->NodePosX = X; VS->NodePosY = Y;
                Graph->AddNode(VS, true, false);
                VS->AllocateDefaultPins();
                Created = VS;
            }
            else if (Type == TEXT("sequence"))
            {
                UK2Node_ExecutionSequence* SN = NewObject<UK2Node_ExecutionSequence>(Graph);
                SN->NodePosX = X; SN->NodePosY = Y;
                Graph->AddNode(SN, true, false);
                SN->AllocateDefaultPins();
                Created = SN;
            }
            else { return FString::Printf(TEXT("Error: Unknown type: %s"), *Type); }

            if (Created)
            {
                const TSharedPtr<FJsonObject>* DefaultsObj;
                if (N->TryGetObjectField(TEXT("defaults"), DefaultsObj))
                    for (auto& KV : (*DefaultsObj)->Values)
                    {
                        UEdGraphPin* Pin = FindPinByName(Created, KV.Key, -1);
                        FString StrVal;
                        if (Pin && KV.Value->TryGetString(StrVal))
                            Pin->DefaultValue = StrVal;
                    }
                NodeMap.Add(Id, Created);
                ++NodesCreated;
            }
        }
    }

    const TArray<TSharedPtr<FJsonValue>>* ConnsArr;
    if (Root->TryGetArrayField(TEXT("connections"), ConnsArr))
    {
        for (const auto& V : *ConnsArr)
        {
            const TSharedPtr<FJsonObject> C = V->AsObject();
            if (!C.IsValid()) continue;
            FString FromId  = C->GetStringField(TEXT("from"));
            FString FromPin = C->GetStringField(TEXT("fp"));
            FString ToId    = C->GetStringField(TEXT("to"));
            FString ToPin   = C->GetStringField(TEXT("tp"));
            UEdGraphNode** pFrom = NodeMap.Find(FromId);
            UEdGraphNode** pTo   = NodeMap.Find(ToId);
            if (!pFrom) return FString::Printf(TEXT("Error: Source not found: %s"), *FromId);
            if (!pTo)   return FString::Printf(TEXT("Error: Target not found: %s"), *ToId);
            UEdGraphPin* PinA = FindPinByName(*pFrom, FromPin, 0);
            UEdGraphPin* PinB = FindPinByName(*pTo,   ToPin,   1);
            if (!PinA) return FString::Printf(TEXT("Error: Output pin not found: %s on %s"), *FromPin, *FromId);
            if (!PinB) return FString::Printf(TEXT("Error: Input pin not found: %s on %s"), *ToPin, *ToId);
            Graph->GetSchema()->TryCreateConnection(PinA, PinB);
            ++ConnsCreated;
        }
    }

    FBlueprintEditorUtils::MarkBlueprintAsModified(Blueprint);
    return FString::Printf(TEXT("OK: %d nodes, %d connections"), NodesCreated, ConnsCreated);
}

// ── MoveFolder ───────────────────────────────────────────────────────────────
// Équivalent drag&drop Content Browser : déplace tous les assets d'un dossier
// vers un autre et met à jour toutes les références (crée des redirectors propres).
// Usage Python : bpes.move_folder("/Game/IA", "/Game/HorrorGame/IA")

FString UBlueprintEditingSubsystem::MoveFolder(const FString& SourcePath, const FString& DestPath)
{
    // ── 1. Validation pré-move ────────────────────────────────────────────────
    IAssetRegistry& AR = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry").Get();

    TArray<FAssetData> Assets;
    AR.GetAssetsByPath(FName(*SourcePath), Assets, /*bRecursive=*/true);

    if (Assets.Num() == 0)
        return FString::Printf(TEXT("Error: No assets found in %s"), *SourcePath);

    // ── 2. Construire les FAssetRenameData ────────────────────────────────────
    IAssetTools& AssetTools = FModuleManager::LoadModuleChecked<FAssetToolsModule>("AssetTools").Get();
    TArray<FAssetRenameData> RenameData;

    for (const FAssetData& Asset : Assets)
    {
        // Ex: /Game/IA/Blueprint/Enemy  →  /Game/HorrorGame/IA/Blueprint/Enemy
        FString OldPackagePath = Asset.PackagePath.ToString();
        FString NewPackagePath = OldPackagePath.Replace(*SourcePath, *DestPath, ESearchCase::CaseSensitive);

        RenameData.Add(FAssetRenameData(
            Asset.GetAsset(),
            NewPackagePath,
            Asset.AssetName.ToString()
        ));
    }

    // ── 3. Move (synchrone, met à jour les références et crée les redirectors) ──
    bool bSuccess = AssetTools.RenameAssets(RenameData);

    if (!bSuccess)
        return FString::Printf(TEXT("Error: RenameAssets reported failure for %s → %s"), *SourcePath, *DestPath);

    // ── 4. Vérification post-move ─────────────────────────────────────────────
    TArray<FAssetData> DestAssets;
    AR.GetAssetsByPath(FName(*DestPath), DestAssets, /*bRecursive=*/true);

    if (DestAssets.Num() == 0)
        return FString::Printf(TEXT("Error: Destination %s is empty after move — assets may be lost!"), *DestPath);

    return FString::Printf(TEXT("OK: %d assets moved from %s to %s (%d at destination)"),
        RenameData.Num(), *SourcePath, *DestPath, DestAssets.Num());
}
