#include "SClaudeChatPanel.h"
#include "ClaudeEditorSubsystem.h"
#include "Editor.h"

#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SSeparator.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Input/SMultiLineEditableTextBox.h"
#include "Widgets/Input/SEditableTextBox.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SCheckBox.h"
#include "Widgets/Text/STextBlock.h"
#include "Widgets/SBoxPanel.h"
#include "Styling/AppStyle.h"
#include "Styling/CoreStyle.h"

#define LOCTEXT_NAMESPACE "ClaudeChatPanel"

// ---------------------------------------------------------------------------

UClaudeEditorSubsystem* SClaudeChatPanel::GetSub() const
{
    return GEditor ? GEditor->GetEditorSubsystem<UClaudeEditorSubsystem>() : nullptr;
}

// ---------------------------------------------------------------------------
// Construct
// ---------------------------------------------------------------------------

void SClaudeChatPanel::Construct(const FArguments& InArgs)
{
    // Bind delegates (AddRaw — RemoveAll dans le destructeur)
    if (UClaudeEditorSubsystem* Sub = GetSub())
    {
        Sub->OnMessage .AddRaw(this, &SClaudeChatPanel::OnClaudeMessage);
        Sub->OnThinking.AddRaw(this, &SClaudeChatPanel::OnClaudeThinking);
        Sub->OnDone    .AddRaw(this, &SClaudeChatPanel::OnClaudeDone);
    }

    ChildSlot
    [
        SNew(SVerticalBox)

        // ── En-tete ─────────────────────────────────────────────────────────
        + SVerticalBox::Slot()
        .AutoHeight()
        .Padding(6.f, 6.f, 6.f, 4.f)
        [
            SNew(SHorizontalBox)
            + SHorizontalBox::Slot().FillWidth(1.f).VAlign(VAlign_Center)
            [
                SNew(STextBlock)
                .Text(LOCTEXT("Title", "Claude AI — HorrorGame"))
                .Font(FCoreStyle::GetDefaultFontStyle("Bold", 11))
            ]
            + SHorizontalBox::Slot().AutoWidth()
            [
                SNew(SButton)
                .Text(LOCTEXT("Clear", "Effacer"))
                .ToolTipText(LOCTEXT("ClearTip", "Efface l'historique de conversation"))
                .OnClicked_Lambda([this]() -> FReply
                {
                    if (UClaudeEditorSubsystem* Sub = GetSub()) Sub->ClearHistory();
                    if (MessagesBox.IsValid()) MessagesBox->ClearChildren();
                    return FReply::Handled();
                })
            ]
        ]

        + SVerticalBox::Slot().AutoHeight()
        [ SNew(SSeparator) ]

        // ── Historique ──────────────────────────────────────────────────────
        + SVerticalBox::Slot()
        .FillHeight(1.f)
        [
            SAssignNew(ScrollBox, SScrollBox)
            + SScrollBox::Slot()
            [
                SAssignNew(MessagesBox, SVerticalBox)
            ]
        ]

        // ── Indicateur "Claude reflechit" ───────────────────────────────────
        + SVerticalBox::Slot()
        .AutoHeight()
        .Padding(8.f, 2.f)
        [
            SAssignNew(ThinkingLabel, STextBlock)
            .Text(LOCTEXT("Thinking", "Claude reflechit..."))
            .ColorAndOpacity(FSlateColor(FLinearColor(0.55f, 0.75f, 1.f)))
            .Visibility(EVisibility::Collapsed)
        ]

        + SVerticalBox::Slot().AutoHeight()
        [ SNew(SSeparator) ]

        // ── Cle API ─────────────────────────────────────────────────────────
        + SVerticalBox::Slot()
        .AutoHeight()
        .Padding(6.f, 3.f)
        [
            SNew(SHorizontalBox)
            + SHorizontalBox::Slot()
            .AutoWidth().VAlign(VAlign_Center)
            .Padding(0.f, 0.f, 6.f, 0.f)
            [
                SNew(STextBlock)
                .Text(LOCTEXT("ApiKeyLabel", "Cle API :"))
                .Font(FCoreStyle::GetDefaultFontStyle("Regular", 8))
                .ColorAndOpacity(FSlateColor(FLinearColor(0.65f, 0.65f, 0.65f)))
            ]
            + SHorizontalBox::Slot().FillWidth(1.f)
            [
                SAssignNew(ApiKeyBox, SEditableTextBox)
                .HintText(LOCTEXT("ApiKeyHint", "sk-ant-...  (console.anthropic.com — ou var env ANTHROPIC_API_KEY)"))
                .IsPassword(true)
                .Font(FCoreStyle::GetDefaultFontStyle("Regular", 8))
                .OnTextChanged(this, &SClaudeChatPanel::OnApiKeyChanged)
            ]
        ]

        // ── Vision (joindre un screenshot au prochain message) ──────────────
        + SVerticalBox::Slot()
        .AutoHeight()
        .Padding(6.f, 0.f, 6.f, 3.f)
        [
            SNew(SHorizontalBox)
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
            [
                SAssignNew(ScreenshotCheckBox, SCheckBox)
                .IsChecked(ECheckBoxState::Unchecked)
                .OnCheckStateChanged_Lambda([this](ECheckBoxState NewState)
                {
                    if (UClaudeEditorSubsystem* Sub = GetSub())
                    {
                        Sub->bAttachScreenshot = (NewState == ECheckBoxState::Checked);
                    }
                })
            ]
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(4.f, 0.f, 0.f, 0.f)
            [
                SNew(STextBlock)
                .Text(LOCTEXT("VisionLabel", "Vision : joindre un screenshot (position actuelle du viewport) au prochain message"))
                .Font(FCoreStyle::GetDefaultFontStyle("Regular", 8))
                .ColorAndOpacity(FSlateColor(FLinearColor(0.65f, 0.65f, 0.65f)))
            ]
        ]

        // ── Zone de saisie ──────────────────────────────────────────────────
        + SVerticalBox::Slot()
        .AutoHeight()
        .Padding(6.f, 4.f, 6.f, 6.f)
        [
            SNew(SHorizontalBox)
            + SHorizontalBox::Slot().FillWidth(1.f)
            [
                SAssignNew(InputBox, SMultiLineEditableTextBox)
                .HintText(LOCTEXT("InputHint",
                    "Donne une instruction... (Entree = envoyer, Maj+Entree = saut de ligne)"))
                .AutoWrapText(true)
                .OnKeyDownHandler(this, &SClaudeChatPanel::OnInputKeyDown)
            ]
            + SHorizontalBox::Slot()
            .AutoWidth()
            .Padding(4.f, 0.f, 0.f, 0.f)
            .VAlign(VAlign_Bottom)
            [
                SNew(SButton)
                .Text(LOCTEXT("Send", "Envoyer"))
                .OnClicked_Lambda([this]() -> FReply
                {
                    OnSendClicked();
                    return FReply::Handled();
                })
            ]
        ]
    ];

    // Message de bienvenue
    AddMessage(
        TEXT("Bonjour ! Je suis ton agent IA pour HorrorGame (propulse par Claude via l'API Anthropic).\n"
             "CLAUDE.md charge — je connais ton API Python, BatchWireGraph, BPGraph DSL "
             "et toute la geometrie du level.\nQue veux-tu faire ?"),
        EMsgRole::Assistant);

    // Afficher si la cle est deja chargee (sans declencher de sauvegarde)
    if (UClaudeEditorSubsystem* Sub = GetSub())
    {
        if (!Sub->ApiKey.IsEmpty() && ApiKeyBox.IsValid())
        {
            bUpdatingProgrammatically = true;
            ApiKeyBox->SetText(FText::FromString(TEXT("(chargee depuis ANTHROPIC_API_KEY)")));
            bUpdatingProgrammatically = false;
        }
    }
}

SClaudeChatPanel::~SClaudeChatPanel()
{
    if (UClaudeEditorSubsystem* Sub = GetSub())
    {
        Sub->OnMessage .RemoveAll(this);
        Sub->OnThinking.RemoveAll(this);
        Sub->OnDone    .RemoveAll(this);
    }
}

// ---------------------------------------------------------------------------
// Envoi
// ---------------------------------------------------------------------------

void SClaudeChatPanel::OnSendClicked()
{
    if (!InputBox.IsValid()) return;

    FString Text = InputBox->GetText().ToString().TrimStartAndEnd();
    if (Text.IsEmpty()) return;

    AddMessage(Text, EMsgRole::User);
    InputBox->SetText(FText::GetEmpty());

    if (UClaudeEditorSubsystem* Sub = GetSub())
    {
        Sub->SendMessage(Text);
    }
}

FReply SClaudeChatPanel::OnInputKeyDown(const FGeometry& /*Geom*/, const FKeyEvent& Key)
{
    if (Key.GetKey() == EKeys::Enter && !Key.IsShiftDown())
    {
        OnSendClicked();
        return FReply::Handled();
    }
    return FReply::Unhandled();
}

void SClaudeChatPanel::OnApiKeyChanged(const FText& NewText)
{
    // Ignorer les mises a jour programmatiques (ex: affichage du placeholder env var)
    if (bUpdatingProgrammatically) return;

    if (UClaudeEditorSubsystem* Sub = GetSub())
    {
        const FString Key = NewText.ToString().TrimStartAndEnd();
        // Ne pas sauvegarder le texte placeholder
        if (Key == TEXT("(chargee depuis ANTHROPIC_API_KEY)")) return;

        Sub->ApiKey = Key;
        Sub->SaveApiKey();  // sauvegarde dans Saved/Claude/apikey.txt
    }
}

// ---------------------------------------------------------------------------
// Affichage des messages
// ---------------------------------------------------------------------------

void SClaudeChatPanel::AddMessage(const FString& Text, EMsgRole Role)
{
    if (!MessagesBox.IsValid()) return;

    // Couleurs selon le role
    FLinearColor BgColor, TxtColor;
    FString      Prefix;
    FSlateFontInfo Font = FCoreStyle::GetDefaultFontStyle("Regular", 10);

    switch (Role)
    {
    case EMsgRole::User:
        BgColor  = FLinearColor(0.12f, 0.12f, 0.22f, 1.f);
        TxtColor = FLinearColor(0.85f, 0.88f, 1.f,   1.f);
        Prefix   = TEXT("Toi : ");
        break;
    case EMsgRole::Assistant:
        BgColor  = FLinearColor(0.08f, 0.14f, 0.10f, 1.f);
        TxtColor = FLinearColor(0.85f, 1.f,   0.85f, 1.f);
        Prefix   = TEXT("Claude : ");
        break;
    case EMsgRole::Code:
        BgColor  = FLinearColor(0.04f, 0.04f, 0.06f, 1.f);
        TxtColor = FLinearColor(0.75f, 0.90f, 0.55f, 1.f);
        Prefix   = TEXT("");
        Font     = FCoreStyle::GetDefaultFontStyle("Mono", 9);
        break;
    case EMsgRole::Result:
        BgColor  = FLinearColor(0.04f, 0.10f, 0.04f, 1.f);
        TxtColor = FLinearColor(0.55f, 0.95f, 0.55f, 1.f);
        Prefix   = TEXT("");
        break;
    case EMsgRole::Error:
    default:
        BgColor  = FLinearColor(0.20f, 0.05f, 0.05f, 1.f);
        TxtColor = FLinearColor(1.f,   0.55f, 0.55f, 1.f);
        Prefix   = TEXT("Erreur : ");
        break;
    }

    MessagesBox->AddSlot()
    .AutoHeight()
    .Padding(4.f, 2.f)
    [
        SNew(SBorder)
        .BorderImage(FAppStyle::GetBrush("WhiteTexture"))
        .BorderBackgroundColor(BgColor)
        .Padding(FMargin(8.f, 5.f))
        [
            SNew(STextBlock)
            .Text(FText::FromString(Prefix + Text))
            .Font(Font)
            .ColorAndOpacity(FSlateColor(TxtColor))
            .AutoWrapText(true)
        ]
    ];

    ScrollToBottom();
}

void SClaudeChatPanel::ScrollToBottom()
{
    if (ScrollBox.IsValid())
        ScrollBox->ScrollToEnd();
}

// ---------------------------------------------------------------------------
// Delegates depuis UClaudeEditorSubsystem
// ---------------------------------------------------------------------------

void SClaudeChatPanel::OnClaudeMessage(const FString& Text, bool bIsError)
{
    if (bIsError)
    {
        AddMessage(Text, EMsgRole::Error);
    }
    else if (Text.StartsWith(TEXT("```")))
    {
        FString Code = Text;
        Code.RemoveFromStart(TEXT("```python\n"));
        Code.RemoveFromStart(TEXT("```\n"));
        Code.RemoveFromEnd(TEXT("\n```"));
        Code.RemoveFromEnd(TEXT("```"));
        AddMessage(Code, EMsgRole::Code);
    }
    else if (Text.StartsWith(TEXT("Resultat : ")))
    {
        AddMessage(Text, EMsgRole::Result);
    }
    else
    {
        AddMessage(Text, EMsgRole::Assistant);
    }
}

void SClaudeChatPanel::OnClaudeThinking()
{
    if (ThinkingLabel.IsValid())
        ThinkingLabel->SetVisibility(EVisibility::Visible);
}

void SClaudeChatPanel::OnClaudeDone()
{
    if (ThinkingLabel.IsValid())
        ThinkingLabel->SetVisibility(EVisibility::Collapsed);
}

#undef LOCTEXT_NAMESPACE
