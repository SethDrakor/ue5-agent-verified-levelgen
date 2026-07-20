#include "ClaudeEditorSubsystem.h"
#include "HttpModule.h"
#include "Interfaces/IHttpResponse.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "Misc/Paths.h"
#include "Misc/FileHelper.h"
#include "HAL/PlatformMisc.h"
#include "HAL/FileManager.h"
#include "Modules/ModuleManager.h"
#include "Editor.h"
#include "Misc/Base64.h"

// ---------------------------------------------------------------------------
// Initialize
// ---------------------------------------------------------------------------

void UClaudeEditorSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
    Super::Initialize(Collection);

    // Priorite 1 : variable d'environnement
    ApiKey = FPlatformMisc::GetEnvironmentVariable(TEXT("ANTHROPIC_API_KEY"));

    // Priorite 2 : fichier de config persistant (si env var absente)
    if (ApiKey.IsEmpty())
    {
        FString KeyFilePath = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Claude"), TEXT("apikey.txt"));
        FFileHelper::LoadFileToString(ApiKey, *KeyFilePath);
        ApiKey = ApiKey.TrimStartAndEnd();
        // Ignorer un placeholder (ancien ou nouveau) ou une cle Groq (gsk_...) laissee par une version anterieure
        if (ApiKey == TEXT("(chargee depuis GROQ_API_KEY)") ||
            ApiKey == TEXT("(chargee depuis ANTHROPIC_API_KEY)") ||
            ApiKey.StartsWith(TEXT("gsk_")))
        {
            ApiKey = TEXT("");
            UE_LOG(LogTemp, Warning, TEXT("ClaudePanel: cle Groq/placeholder detectee dans apikey.txt, ignoree. Ressaisir une cle Anthropic (sk-ant-...) dans le panneau."));
        }
        else if (!ApiKey.IsEmpty())
        {
            UE_LOG(LogTemp, Log, TEXT("ClaudePanel: cle API chargee depuis %s"), *KeyFilePath);
        }
    }

    LoadSystemPrompt();
}

void UClaudeEditorSubsystem::SaveApiKey()
{
    FString KeyFilePath = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Claude"), TEXT("apikey.txt"));
    FString Dir         = FPaths::GetPath(KeyFilePath);
    IFileManager::Get().MakeDirectory(*Dir, /*Tree=*/true);
    FFileHelper::SaveStringToFile(ApiKey, *KeyFilePath, FFileHelper::EEncodingOptions::ForceUTF8);
    UE_LOG(LogTemp, Log, TEXT("ClaudePanel: cle API sauvegardee dans %s"), *KeyFilePath);
}

void UClaudeEditorSubsystem::LoadSystemPrompt()
{
    // Priorite 1 : CLAUDE_AGENT.md (prompt court optimise pour l'agent UE5)
    FString AgentMdPath = FPaths::Combine(FPaths::ProjectDir(), TEXT("CLAUDE_AGENT.md"));
    if (FFileHelper::LoadFileToString(SystemPrompt, *AgentMdPath))
    {
        UE_LOG(LogTemp, Log, TEXT("ClaudePanel: CLAUDE_AGENT.md charge (%d chars)."), SystemPrompt.Len());
        return;
    }

    // Fallback : CLAUDE.md tronque a 4000 chars pour rester sous les limites de contexte
    FString ClaudeMdPath = FPaths::Combine(FPaths::ProjectDir(), TEXT("CLAUDE.md"));
    if (FFileHelper::LoadFileToString(SystemPrompt, *ClaudeMdPath))
    {
        if (SystemPrompt.Len() > 4000)
        {
            SystemPrompt = SystemPrompt.Left(4000);
            SystemPrompt += TEXT("\n[...tronque pour limites de contexte...]");
        }
        UE_LOG(LogTemp, Log, TEXT("ClaudePanel: CLAUDE.md charge (%d chars)."), SystemPrompt.Len());
    }
    else
    {
        SystemPrompt = TEXT("Tu es un expert Unreal Engine 5.7 integre dans l'editeur. "
                            "Utilise execute_python pour toute action dans UE5. "
                            "Commence par `from agent_core import *` (ou `from ue5_utils import *` "
                            "selon le projet).");
        UE_LOG(LogTemp, Warning, TEXT("ClaudePanel: aucun fichier prompt trouve, defaut utilise."));
    }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

void UClaudeEditorSubsystem::SendMessage(const FString& UserMessage)
{
    if (bIsProcessing) return;

    if (ApiKey.IsEmpty())
    {
        OnMessage.Broadcast(
            TEXT("Cle API manquante.\n"
                 "1. Cree un compte sur console.anthropic.com\n"
                 "2. Cree une cle API (commence par sk-ant-)\n"
                 "3. Colle-la dans le champ 'Cle API' ci-dessous\n"
                 "   OU definis la variable d'environnement ANTHROPIC_API_KEY"), true);
        return;
    }

    bIsProcessing = true;
    OnThinking.Broadcast();

    // Si demande, capturer un screenshot AVANT de notifier "thinking" au sens API — la
    // capture elle-meme est synchrone (GEditor->Exec bloquant) donc pas besoin d'un etat
    // intermediaire supplementaire.
    FString ScreenshotBase64;
    if (bAttachScreenshot)
    {
        ScreenshotBase64 = CaptureViewportScreenshotBase64();
        if (ScreenshotBase64.IsEmpty())
        {
            OnMessage.Broadcast(
                TEXT("Capture de screenshot echouee — message envoye en texte seul "
                     "(voir Output Log pour le detail)."), true);
        }
    }

    // Ajouter le message utilisateur a l'historique.
    // Format Anthropic : "content" peut etre une simple string (texte seul) OU un tableau
    // de blocs {"type":"text",...}/{"type":"image",...} quand une image est attachee.
    TSharedPtr<FJsonObject> UserMsg = MakeShareable(new FJsonObject);
    UserMsg->SetStringField(TEXT("role"), TEXT("user"));

    if (ScreenshotBase64.IsEmpty())
    {
        UserMsg->SetStringField(TEXT("content"), UserMessage);
    }
    else
    {
        TSharedPtr<FJsonObject> ImgSource = MakeShareable(new FJsonObject);
        ImgSource->SetStringField(TEXT("type"),       TEXT("base64"));
        ImgSource->SetStringField(TEXT("media_type"), TEXT("image/png"));
        ImgSource->SetStringField(TEXT("data"),       ScreenshotBase64);

        TSharedPtr<FJsonObject> ImgBlock = MakeShareable(new FJsonObject);
        ImgBlock->SetStringField(TEXT("type"), TEXT("image"));
        ImgBlock->SetObjectField(TEXT("source"), ImgSource);

        TSharedPtr<FJsonObject> TextBlock = MakeShareable(new FJsonObject);
        TextBlock->SetStringField(TEXT("type"), TEXT("text"));
        TextBlock->SetStringField(TEXT("text"), UserMessage);

        // Image avant le texte (recommandation Anthropic : ameliore la qualite quand le
        // texte fait reference a l'image, ex. "est-ce que cette salle est trop sombre ?").
        TArray<TSharedPtr<FJsonValue>> ContentBlocks;
        ContentBlocks.Add(MakeShareable(new FJsonValueObject(ImgBlock)));
        ContentBlocks.Add(MakeShareable(new FJsonValueObject(TextBlock)));
        UserMsg->SetArrayField(TEXT("content"), ContentBlocks);

        OnMessage.Broadcast(TEXT("[Screenshot attache a ce message]"), false);
    }

    History.Add(UserMsg);

    CallApi();
}

void UClaudeEditorSubsystem::ClearHistory()
{
    History.Empty();
    bIsProcessing = false;
}

// ---------------------------------------------------------------------------
// HTTP call — API Anthropic Messages (https://api.anthropic.com/v1/messages)
// ---------------------------------------------------------------------------

void UClaudeEditorSubsystem::CallApi()
{
    // --- Tableau messages : uniquement user/assistant. Le system prompt est un
    // champ racine a part chez Anthropic (pas un message role="system") ---
    TArray<TSharedPtr<FJsonValue>> MessagesArr;
    for (const TSharedPtr<FJsonObject>& Msg : History)
    {
        MessagesArr.Add(MakeShareable(new FJsonValueObject(Msg)));
    }

    // --- Definition de l'outil (format Anthropic : input_schema, pas nested "function") ---
    TSharedPtr<FJsonObject> CodeProp = MakeShareable(new FJsonObject);
    CodeProp->SetStringField(TEXT("type"),
        TEXT("string"));
    CodeProp->SetStringField(TEXT("description"),
        TEXT("Code Python a executer dans UE5.7. "
             "Utilise agent_core (ou ue5_utils), BPGraph DSL, BatchWireGraph, subsystems C++ custom."));

    TSharedPtr<FJsonObject> Props = MakeShareable(new FJsonObject);
    Props->SetObjectField(TEXT("code"), CodeProp);

    TArray<TSharedPtr<FJsonValue>> Required;
    Required.Add(MakeShareable(new FJsonValueString(TEXT("code"))));

    TSharedPtr<FJsonObject> InputSchema = MakeShareable(new FJsonObject);
    InputSchema->SetStringField(TEXT("type"),       TEXT("object"));
    InputSchema->SetObjectField(TEXT("properties"), Props);
    InputSchema->SetArrayField(TEXT("required"),    Required);

    TSharedPtr<FJsonObject> Tool = MakeShareable(new FJsonObject);
    Tool->SetStringField(TEXT("name"),        TEXT("execute_python"));
    Tool->SetStringField(TEXT("description"),
        TEXT("Execute du code Python dans Unreal Engine 5.7 editor. "
             "Acces complet : agent_core/ue5_utils, BPGraph DSL, BatchWireGraph, "
             "subsystems custom du projet."));
    Tool->SetObjectField(TEXT("input_schema"), InputSchema);

    TArray<TSharedPtr<FJsonValue>> ToolsArr;
    ToolsArr.Add(MakeShareable(new FJsonValueObject(Tool)));

    // --- Payload racine ---
    TSharedPtr<FJsonObject> Payload = MakeShareable(new FJsonObject);
    Payload->SetStringField(TEXT("model"),      Model);
    Payload->SetNumberField(TEXT("max_tokens"), 4096);
    Payload->SetStringField(TEXT("system"),     SystemPrompt);
    Payload->SetArrayField(TEXT("messages"),    MessagesArr);
    Payload->SetArrayField(TEXT("tools"),       ToolsArr);

    FString JsonBody;
    TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&JsonBody);
    FJsonSerializer::Serialize(Payload.ToSharedRef(), Writer);

    // --- Requete HTTP — auth via x-api-key + anthropic-version (pas de Bearer) ---
    TSharedRef<IHttpRequest, ESPMode::ThreadSafe> Request =
        FHttpModule::Get().CreateRequest();
    Request->SetURL(TEXT("https://api.anthropic.com/v1/messages"));
    Request->SetVerb(TEXT("POST"));
    Request->SetHeader(TEXT("x-api-key"), ApiKey);
    Request->SetHeader(TEXT("anthropic-version"), TEXT("2023-06-01"));
    Request->SetHeader(TEXT("content-type"), TEXT("application/json"));
    Request->SetContentAsString(JsonBody);
    // Sans timeout explicite, une requete qui ne recoit jamais de reponse (reseau mort,
    // API qui pend) ne declenche jamais OnHttpResponse -> bIsProcessing reste bloque a
    // "true" pour toujours et le panneau se fige sans aucun message d'erreur. 45s laisse
    // de la marge pour une reponse avec tool_use (plus lente qu'un simple texte) tout en
    // bornant l'attente a une duree raisonnable pour un usage interactif.
    Request->SetTimeout(45.0f);
    Request->OnProcessRequestComplete().BindUObject(
        this, &UClaudeEditorSubsystem::OnHttpResponse);
    Request->ProcessRequest();
}

// ---------------------------------------------------------------------------
// HTTP response
// ---------------------------------------------------------------------------

void UClaudeEditorSubsystem::OnHttpResponse(
    FHttpRequestPtr /*Request*/, FHttpResponsePtr Response, bool bWasSuccessful)
{
    if (!bWasSuccessful || !Response.IsValid())
    {
        bIsProcessing = false;
        OnMessage.Broadcast(TEXT("Echec de la requete HTTP. Verifie ta connexion."), true);
        OnDone.Broadcast();
        return;
    }

    const int32 Code = Response->GetResponseCode();
    const FString Body = Response->GetContentAsString();

    if (Code != 200)
    {
        bIsProcessing = false;
        // 401 = cle invalide, 429 = rate limit/credit epuise, 529 = surcharge — le Body
        // Anthropic contient un message d'erreur exploitable tel quel.
        OnMessage.Broadcast(FString::Printf(TEXT("Erreur API %d : %s"), Code, *Body), true);
        OnDone.Broadcast();
        return;
    }

    TSharedPtr<FJsonObject> RespObj;
    TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Body);
    if (!FJsonSerializer::Deserialize(Reader, RespObj) || !RespObj.IsValid())
    {
        bIsProcessing = false;
        OnMessage.Broadcast(TEXT("Reponse JSON invalide."), true);
        OnDone.Broadcast();
        return;
    }

    HandleResponse(RespObj);
}

void UClaudeEditorSubsystem::HandleResponse(TSharedPtr<FJsonObject> ResponseObj)
{
    // Format Anthropic : {"role":"assistant","content":[{"type":"text","text":...} |
    // {"type":"tool_use","id":...,"name":...,"input":{...}}], "stop_reason":"tool_use"|"end_turn"|...}
    const TArray<TSharedPtr<FJsonValue>>* ContentArr = nullptr;
    if (!ResponseObj->TryGetArrayField(TEXT("content"), ContentArr))
    {
        bIsProcessing = false;
        FString ErrMsg;
        const TSharedPtr<FJsonObject>* ErrObjPtr = nullptr;
        if (ResponseObj->TryGetObjectField(TEXT("error"), ErrObjPtr))
        {
            (*ErrObjPtr)->TryGetStringField(TEXT("message"), ErrMsg);
        }
        OnMessage.Broadcast(
            ErrMsg.IsEmpty() ? TEXT("Champ 'content' manquant dans la reponse.") : ErrMsg,
            true);
        OnDone.Broadcast();
        return;
    }

    FString StopReason;
    ResponseObj->TryGetStringField(TEXT("stop_reason"), StopReason);

    // Afficher les blocs texte au fur et a mesure, collecter les tool_use
    struct FPendingToolUse { FString Id; FString Name; TSharedPtr<FJsonObject> Input; };
    TArray<FPendingToolUse> PendingTools;

    for (const TSharedPtr<FJsonValue>& BlockVal : *ContentArr)
    {
        TSharedPtr<FJsonObject> Block = BlockVal->AsObject();
        if (!Block.IsValid()) continue;

        FString BlockType;
        Block->TryGetStringField(TEXT("type"), BlockType);

        if (BlockType == TEXT("text"))
        {
            FString Text;
            if (Block->TryGetStringField(TEXT("text"), Text) && !Text.IsEmpty())
            {
                OnMessage.Broadcast(Text, false);
            }
        }
        else if (BlockType == TEXT("tool_use"))
        {
            FPendingToolUse Pending;
            Block->TryGetStringField(TEXT("id"),   Pending.Id);
            Block->TryGetStringField(TEXT("name"), Pending.Name);
            const TSharedPtr<FJsonObject>* InputPtr = nullptr;
            if (Block->TryGetObjectField(TEXT("input"), InputPtr))
            {
                Pending.Input = *InputPtr;
            }
            PendingTools.Add(Pending);
        }
    }

    if (StopReason == TEXT("tool_use") && PendingTools.Num() > 0)
    {
        // 1. Sauvegarder le message assistant EXACTEMENT tel que recu (Anthropic exige
        //    que les blocs tool_use renvoyes en historique soient identiques a l'original).
        TSharedPtr<FJsonObject> AssistantMsg = MakeShareable(new FJsonObject);
        AssistantMsg->SetStringField(TEXT("role"), TEXT("assistant"));
        AssistantMsg->SetArrayField(TEXT("content"), *ContentArr);
        History.Add(AssistantMsg);

        // 2. Executer chaque outil, construire un message "user" contenant TOUS les
        //    tool_result correspondants (Anthropic veut un seul message user regroupant
        //    les resultats quand plusieurs tool_use arrivent dans la meme reponse).
        TArray<TSharedPtr<FJsonValue>> ToolResultBlocks;

        for (const FPendingToolUse& Pending : PendingTools)
        {
            FString ToolResult;
            if (Pending.Name == TEXT("execute_python"))
            {
                FString Code;
                if (Pending.Input.IsValid())
                {
                    Pending.Input->TryGetStringField(TEXT("code"), Code);
                }

                OnMessage.Broadcast(FString::Printf(TEXT("```python\n%s\n```"), *Code), false);
                ToolResult = ExecutePython(Code);
                OnMessage.Broadcast(FString::Printf(TEXT("Resultat : %s"), *ToolResult), false);
            }
            else
            {
                ToolResult = FString::Printf(TEXT("Outil inconnu : %s"), *Pending.Name);
            }

            TSharedPtr<FJsonObject> ToolResultBlock = MakeShareable(new FJsonObject);
            ToolResultBlock->SetStringField(TEXT("type"),         TEXT("tool_result"));
            ToolResultBlock->SetStringField(TEXT("tool_use_id"),  Pending.Id);
            ToolResultBlock->SetStringField(TEXT("content"),      ToolResult);
            ToolResultBlocks.Add(MakeShareable(new FJsonValueObject(ToolResultBlock)));
        }

        TSharedPtr<FJsonObject> ToolResultsMsg = MakeShareable(new FJsonObject);
        ToolResultsMsg->SetStringField(TEXT("role"), TEXT("user"));
        ToolResultsMsg->SetArrayField(TEXT("content"), ToolResultBlocks);
        History.Add(ToolResultsMsg);

        // 3. Rappeler l'API pour la suite de la conversation
        OnThinking.Broadcast();
        CallApi();
        return;
    }

    // Pas de tool_use (stop_reason == "end_turn"/"max_tokens"/...) : sauvegarder le
    // message assistant tel quel et terminer.
    TSharedPtr<FJsonObject> AssistantMsg = MakeShareable(new FJsonObject);
    AssistantMsg->SetStringField(TEXT("role"), TEXT("assistant"));
    AssistantMsg->SetArrayField(TEXT("content"), *ContentArr);
    History.Add(AssistantMsg);

    bIsProcessing = false;
    OnDone.Broadcast();
}

// ---------------------------------------------------------------------------
// Vision — capture ecran (delegue au pipeline Python deja valide)
// ---------------------------------------------------------------------------

FString UClaudeEditorSubsystem::CaptureViewportScreenshotBase64()
{
    // Reutilise get_live_viewport_transform()/capture_reference_screenshot() de ue5_utils.py
    // plutot que de reimplementer le SceneCaptureComponent2D + export RTF_RGBA8 en C++ — ce
    // pipeline existe deja et est explicitement valide contre le piege EXR/PNG documente dans
    // CLAUDE.md ("Screenshot fiable"). Le project Content/Python/ est deja sur sys.path via
    // le PythonScriptPlugin, pas besoin de le rajouter ici.
    //
    // Marqueur unique plutot que "le chemin est la derniere ligne imprimee" : verifie en
    // conditions reelles (via mcp__ue5-mcp__ue5_execute) que le premier import de ue5_utils
    // dans une session declenche un vrai print("[ue5_utils] loaded ...") au niveau module —
    // se fier a la derniere ligne aurait marche par chance la plupart du temps et echoue de
    // facon sournoise (mauvaise image envoyee) exactement au premier appel de la session.
    static const FString Marker = TEXT("CLAUDE_PANEL_SCREENSHOT_PATH::");

    const FString CaptureScript = FString::Printf(
        TEXT("from ue5_utils import capture_reference_screenshot, get_live_viewport_transform\n")
        TEXT("x, y, z, pitch, yaw, roll = get_live_viewport_transform()\n")
        TEXT("_p = capture_reference_screenshot(x, y, z, pitch=pitch, yaw=yaw, roll=roll, name='claude_panel_vision')\n")
        TEXT("print('%s' + _p)\n"),
        *Marker);

    const FString RawOutput = ExecutePython(CaptureScript);

    int32 MarkerIdx = RawOutput.Find(Marker, ESearchCase::CaseSensitive, ESearchDir::FromEnd);
    if (MarkerIdx == INDEX_NONE)
    {
        UE_LOG(LogTemp, Warning,
            TEXT("ClaudePanel: marqueur de capture introuvable dans la sortie : %s"), *RawOutput);
        return FString();
    }

    FString PngPath = RawOutput.Mid(MarkerIdx + Marker.Len());
    int32 NewlineIdx;
    if (PngPath.FindChar(TEXT('\n'), NewlineIdx))
    {
        PngPath = PngPath.Left(NewlineIdx);
    }
    PngPath.TrimStartAndEndInline();

    // Verifier que ca ressemble bien a un PNG existant avant de charger, plutot que de
    // tenter LoadFileToArray sur une valeur inattendue et echouer plus loin avec un
    // message moins clair.
    if (!PngPath.EndsWith(TEXT(".png")) || !FPaths::FileExists(PngPath))
    {
        UE_LOG(LogTemp, Warning,
            TEXT("ClaudePanel: capture screenshot echouee, chemin extrait : %s"), *PngPath);
        return FString();
    }

    TArray<uint8> PngBytes;
    if (!FFileHelper::LoadFileToArray(PngBytes, *PngPath))
    {
        UE_LOG(LogTemp, Warning, TEXT("ClaudePanel: impossible de lire %s"), *PngPath);
        return FString();
    }

    return FBase64::Encode(PngBytes);
}

// ---------------------------------------------------------------------------
// Python execution — via fichier temporaire + commande console "py"
// Ne necessite pas WITH_PYTHON ni IPythonScriptPlugin au compile time.
// ---------------------------------------------------------------------------

FString UClaudeEditorSubsystem::ExecutePython(const FString& Code)
{
    if (!GEditor)
    {
        return TEXT("ERREUR : GEditor non disponible.");
    }

    // Suffixe unique par appel — evite qu'un second execute_python (meme reponse, tool_use
    // multiple ; ou appel suivant pendant qu'un ancien fichier traine) n'ecrase les fichiers
    // temporaires d'un appel precedent avant qu'ils aient ete relus, et garde une trace de
    // chaque script execute dans Saved/Claude/ pour le debug.
    const FString Suffix = FString::Printf(TEXT("_%06d"), ++PythonExecCounter);

    FString TempDir    = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Claude"));
    FString ExecFile   = FPaths::Combine(TempDir, TEXT("_exec")   + Suffix + TEXT(".py"));
    FString WrapFile   = FPaths::Combine(TempDir, TEXT("_wrap")   + Suffix + TEXT(".py"));
    FString OutputFile = FPaths::Combine(TempDir, TEXT("_output") + Suffix + TEXT(".txt"));
    IFileManager::Get().MakeDirectory(*TempDir, true);

    // 1. Ecrire le code utilisateur
    if (!FFileHelper::SaveStringToFile(Code, *ExecFile, FFileHelper::EEncodingOptions::ForceUTF8))
        return TEXT("ERREUR : impossible d'ecrire _exec.py");

    // Chemins normalises (forward slashes pour Python)
    FString ExecPath   = ExecFile;   ExecPath  .ReplaceInline(TEXT("\\"), TEXT("/"));
    FString OutputPath = OutputFile; OutputPath.ReplaceInline(TEXT("\\"), TEXT("/"));

    // 2. Wrapper qui capture stdout/stderr dans _output.txt
    FString Wrapper = FString::Printf(
        TEXT("import sys, io, traceback\n")
        TEXT("_so, _se = sys.stdout, sys.stderr\n")
        TEXT("_buf = io.StringIO()\n")
        TEXT("sys.stdout = sys.stderr = _buf\n")
        TEXT("try:\n")
        TEXT("    with open(r'%s', encoding='utf-8') as _f:\n")
        TEXT("        exec(_f.read(), globals())\n")
        TEXT("except Exception:\n")
        TEXT("    traceback.print_exc()\n")
        TEXT("finally:\n")
        TEXT("    sys.stdout, sys.stderr = _so, _se\n")
        TEXT("_r = _buf.getvalue().strip()\n")
        TEXT("open(r'%s', 'w', encoding='utf-8').write(_r if _r else 'OK')\n"),
        *ExecPath, *OutputPath
    );

    if (!FFileHelper::SaveStringToFile(Wrapper, *WrapFile, FFileHelper::EEncodingOptions::ForceUTF8))
        return TEXT("ERREUR : impossible d'ecrire _wrap.py");

    // 3. Executer le wrapper
    FString WrapPath = WrapFile;
    WrapPath.ReplaceInline(TEXT("\\"), TEXT("/"));
    GEditor->Exec(GEditor->GetEditorWorldContext().World(),
                  *FString::Printf(TEXT("py \"%s\""), *WrapPath));

    // 4. Lire la sortie capturee
    FString Output;
    if (FFileHelper::LoadFileToString(Output, *OutputFile))
    {
        Output = Output.TrimStartAndEnd();
        // Tronquer si trop long (eviter de saturer le contexte LLM)
        if (Output.Len() > 2000)
            Output = Output.Left(2000) + TEXT("\n[...tronque]");
        return Output;
    }

    return TEXT("OK (pas de sortie capturee — verifier Output Log)");
}
