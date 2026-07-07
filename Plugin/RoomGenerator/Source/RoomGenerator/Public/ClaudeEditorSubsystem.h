#pragma once
#include "CoreMinimal.h"
#include "EditorSubsystem.h"
#include "Http.h"
#include "Dom/JsonObject.h"
#include "ClaudeEditorSubsystem.generated.h"

// Delegates — broadcast sur le Game Thread
DECLARE_MULTICAST_DELEGATE_TwoParams(FOnClaudeMessage,  const FString& /*Text*/, bool /*bIsError*/);
DECLARE_MULTICAST_DELEGATE(FOnClaudeThinking);
DECLARE_MULTICAST_DELEGATE(FOnClaudeDone);

UCLASS()
class ROOMGENERATOR_API UClaudeEditorSubsystem : public UEditorSubsystem
{
    GENERATED_BODY()

public:
    virtual void Initialize(FSubsystemCollectionBase& Collection) override;

    /** Envoie un message utilisateur ; les delegates notifient le panneau en retour. */
    void SendMessage(const FString& UserMessage);

    /** Efface l'historique de conversation. */
    void ClearHistory();

    /** Execute du Python dans l'editeur via IPythonScriptPlugin. */
    FString ExecutePython(const FString& Code);

    /** Cle API Anthropic — lue depuis ANTHROPIC_API_KEY, le fichier de config, ou saisie dans le panel. */
    FString ApiKey;

    /** Modele Claude utilise (voir docs.claude.com pour la liste a jour).
     *  "claude-sonnet-5" = bon compromis prix/qualite par defaut.
     *  Options : "claude-opus-4-8" (plus precis, plus cher), "claude-haiku-4-5-20251001" (rapide/pas cher). */
    FString Model = TEXT("claude-sonnet-5");

    /** Sauvegarde la cle API dans ProjectSaved/Claude/apikey.txt */
    void SaveApiKey();

    FOnClaudeMessage  OnMessage;
    FOnClaudeThinking OnThinking;
    FOnClaudeDone     OnDone;

private:
    TArray<TSharedPtr<FJsonObject>> History;
    FString SystemPrompt;
    bool bIsProcessing = false;

    void LoadSystemPrompt();
    void CallApi();
    void OnHttpResponse(FHttpRequestPtr Request, FHttpResponsePtr Response, bool bWasSuccessful);
    void HandleResponse(TSharedPtr<FJsonObject> ResponseObj);
};
