#include "VignetteManager.h"

#include "EngineUtils.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "Camera/PlayerCameraManager.h"
#include "AIController.h"
#include "BehaviorTree/BlackboardComponent.h"
#include "Kismet/GameplayStatics.h"
#include "Engine/PostProcessVolume.h"

// ------------------------------------------------------------------

AVignetteManager::AVignetteManager()
{
    PrimaryActorTick.bCanEverTick = true;
    SetActorEnableCollision(false);
    // Tag pour que Blueprint puisse trouver cet acteur sans cast
    Tags.Add(FName("VignetteManager"));
}

// ------------------------------------------------------------------

void AVignetteManager::SetPlayerHiding(bool bHiding)
{
    bIsPlayerHiding = bHiding;

    // Quand le joueur se cache : forcer immédiatement tous les ennemis à perdre sa trace
    if (bHiding)
    {
        UWorld* World = GetWorld();
        if (World && World->IsGameWorld())
        {
            ForceEnemiesLosePlayer(World);
        }
    }
}

// ------------------------------------------------------------------

void AVignetteManager::ForceEnemiesLosePlayer(UWorld* World)
{
    for (TActorIterator<APawn> It(World); It; ++It)
    {
        APawn* Pawn = *It;
        if (!Pawn) continue;
        if (!Pawn->GetClass()->GetName().Contains(TEXT("BP_IA_Enemy"))) continue;

        AAIController* AIC = Cast<AAIController>(Pawn->GetController());
        if (!AIC) continue;
        UBlackboardComponent* BB = AIC->GetBlackboardComponent();
        if (!BB) continue;

        BB->SetValueAsBool(TEXT("CanSeePlayer?"), false);
        BB->ClearValue(TEXT("FollowTarget"));
    }
}

// ------------------------------------------------------------------

APostProcessVolume* AVignetteManager::FindUnboundPPV(UWorld* World)
{
    for (TActorIterator<APostProcessVolume> It(World); It; ++It)
    {
        if ((*It)->bUnbound) return *It;
    }
    return nullptr;
}

// ------------------------------------------------------------------

void AVignetteManager::Tick(float DeltaTime)
{
    Super::Tick(DeltaTime);

    UWorld* World = GetWorld();
    if (!World || !World->IsGameWorld()) return;

    // --- 1. Vérifier les ennemis (rate-limited) ---
    CheckTimer += DeltaTime;
    if (CheckTimer >= CHECK_INTERVAL)
    {
        CheckTimer = 0.f;

        if (bIsPlayerHiding)
        {
            // Joueur caché : pas de danger visuel, et on maintient la perte de trace
            ForceEnemiesLosePlayer(World);
            bVignetteActive = false;
        }
        else
        {
            bool bShouldShow = false;
            for (TActorIterator<APawn> It(World); It; ++It)
            {
                APawn* Pawn = *It;
                if (!Pawn) continue;
                if (!Pawn->GetClass()->GetName().Contains(TEXT("BP_IA_Enemy"))) continue;

                AAIController* AIC = Cast<AAIController>(Pawn->GetController());
                if (!AIC) continue;
                UBlackboardComponent* BB = AIC->GetBlackboardComponent();
                if (!BB) continue;

                if (BB->GetValueAsBool(TEXT("CanSeePlayer?")) && !BB->GetValueAsBool(TEXT("IsIlluminated")))
                {
                    bShouldShow = true;
                    break;
                }
            }
            bVignetteActive = bShouldShow;
        }
    }

    // --- 2. PostProcess Volume (cache) ---
    if (!CachedPPV) CachedPPV = FindUnboundPPV(World);
    if (!CachedPPV) return;

    // --- 3. Targets selon état ---
    // En danger : aberration chromatique + légère vignette de bord
    // (référence : Outlast, Alien Isolation — pas d'overlay rouge, visibilité préservée)
    float TargetAberration = BASE_ABERRATION;
    float TargetVignette   = BASE_VIGNETTE;

    if (bVignetteActive)
    {
        PulseTimer += DeltaTime;
        // Pulse sinusoïdal type battement de coeur (~78 bpm)
        float pulse = FMath::Sin(PulseTimer * PULSE_FREQ * PI) * 0.25f + 0.75f;
        TargetAberration = DANGER_ABERRATION * pulse;
        TargetVignette   = DANGER_VIGNETTE   * pulse;
    }
    else
    {
        PulseTimer = 0.f;
    }

    // --- 4. Interpolation douce ---
    CurrentAberration = FMath::FInterpTo(CurrentAberration, TargetAberration, DeltaTime, INTERP_SPEED);
    CurrentVignette   = FMath::FInterpTo(CurrentVignette,   TargetVignette,   DeltaTime, INTERP_SPEED);

    // --- 5. Appliquer au PostProcess Volume ---
    FPostProcessSettings& S = CachedPPV->Settings;
    S.bOverride_SceneFringeIntensity = true;
    S.SceneFringeIntensity           = CurrentAberration;
    S.bOverride_VignetteIntensity    = true;
    S.VignetteIntensity              = CurrentVignette;
}
