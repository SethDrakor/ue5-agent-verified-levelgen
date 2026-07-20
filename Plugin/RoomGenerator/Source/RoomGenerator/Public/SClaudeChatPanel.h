#pragma once
#include "CoreMinimal.h"
#include "Widgets/SCompoundWidget.h"

class SScrollBox;
class SMultiLineEditableTextBox;
class SEditableTextBox;
class SVerticalBox;
class STextBlock;
class SCheckBox;

class SClaudeChatPanel : public SCompoundWidget
{
public:
    SLATE_BEGIN_ARGS(SClaudeChatPanel) {}
    SLATE_END_ARGS()

    void Construct(const FArguments& InArgs);
    virtual ~SClaudeChatPanel();

private:
    enum class EMsgRole { User, Assistant, Code, Result, Error };

    TSharedPtr<SScrollBox>               ScrollBox;
    TSharedPtr<SMultiLineEditableTextBox> InputBox;
    TSharedPtr<SEditableTextBox>          ApiKeyBox;
    TSharedPtr<SVerticalBox>             MessagesBox;
    TSharedPtr<STextBlock>               ThinkingLabel;
    TSharedPtr<SCheckBox>                ScreenshotCheckBox;

    bool bUpdatingProgrammatically = false;

    void OnSendClicked();
    FReply OnInputKeyDown(const FGeometry& Geom, const FKeyEvent& Key);
    void   OnApiKeyChanged(const FText& NewText);

    void AddMessage(const FString& Text, EMsgRole Role);
    void ScrollToBottom();

    void OnClaudeMessage (const FString& Text, bool bIsError);
    void OnClaudeThinking();
    void OnClaudeDone    ();

    class UClaudeEditorSubsystem* GetSub() const;
};
