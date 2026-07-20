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

    /** Si vrai, un screenshot fiable (capture_reference_screenshot cote Python, voir
     *  CLAUDE.md section "Screenshot fiable") de la position ACTUELLE du viewport editeur
     *  est capture et attache comme bloc image au PROCHAIN message envoye au modele.
     *  Sans ce cablage, CallApi() n'a jamais envoye la moindre image malgre un backend
     *  vision-capable (claude-sonnet-5) — le panneau etait aveugle en pratique (voir
     *  CLAUDE.md "REGLE ABSOLUE — l'agent UE5 in-editor ne voit AUCUN screenshot").
     *  Desactive par defaut : une image ajoute des tokens (donc du cout) a chaque envoi,
     *  a activer seulement quand un jugement visuel est reellement necessaire. */
    bool bAttachScreenshot = false;

    FOnClaudeMessage  OnMessage;
    FOnClaudeThinking OnThinking;
    FOnClaudeDone     OnDone;

private:
    TArray<TSharedPtr<FJsonObject>> History;
    FString SystemPrompt;
    bool bIsProcessing = false;

    /** Incremente a chaque appel ExecutePython() — suffixe unique des fichiers temporaires
     *  (_exec/_wrap/_output) pour eviter tout clobber entre deux executions et garder une trace. */
    int32 PythonExecCounter = 0;

    void LoadSystemPrompt();
    void CallApi();
    void OnHttpResponse(FHttpRequestPtr Request, FHttpResponsePtr Response, bool bWasSuccessful);
    void HandleResponse(TSharedPtr<FJsonObject> ResponseObj);

    /** Capture un screenshot a la position actuelle du viewport (delegue au pipeline Python
     *  deja valide : get_live_viewport_transform() + capture_reference_screenshot()) et le
     *  retourne encode en base64. Chaine vide si la capture echoue (n'importe quelle etape :
     *  script Python, fichier PNG absent, lecture disque) — SendMessage() retombe alors sur
     *  un message texte seul plutot que d'echouer silencieusement. */
    FString CaptureViewportScreenshotBase64();
};
