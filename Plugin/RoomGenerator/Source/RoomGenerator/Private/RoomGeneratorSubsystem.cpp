#include "RoomGeneratorSubsystem.h"

#include "Engine/StaticMeshActor.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "Editor.h"
#include "Modules/ModuleManager.h"
#include "RoomGeneratorModule.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/PlayerInput.h"
#include "InputCoreTypes.h"

IMPLEMENT_MODULE(FRoomGeneratorModule, RoomGenerator)

// ---------------------------------------------------------------------------
// Internal helper
// ---------------------------------------------------------------------------

static UWorld* RG_GetEditorWorld()
{
	return GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
}

// ---------------------------------------------------------------------------
// SpawnScaledCube
// ---------------------------------------------------------------------------

AActor* URoomGeneratorSubsystem::SpawnScaledCube(
	UObject* WorldContext, FVector Location, FVector Scale, FString ActorLabel)
{
	// Resolve world: prefer explicit context, fall back to editor world.
	UWorld* World = nullptr;
	if (WorldContext)
	{
		World = GEngine->GetWorldFromContextObject(
			WorldContext, EGetWorldErrorMode::LogAndReturnNull);
	}
	if (!World)
	{
		World = RG_GetEditorWorld();
	}
	if (!World)
	{
		UE_LOG(LogTemp, Error,
			TEXT("RoomGenerator::SpawnScaledCube - cannot resolve a valid World"));
		return nullptr;
	}

	// /Engine/BasicShapes/Cube is always present in any UE5 installation.
	UStaticMesh* CubeMesh = LoadObject<UStaticMesh>(
		nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
	if (!CubeMesh)
	{
		UE_LOG(LogTemp, Error,
			TEXT("RoomGenerator::SpawnScaledCube - failed to load /Engine/BasicShapes/Cube"));
		return nullptr;
	}

	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride =
		ESpawnActorCollisionHandlingMethod::AlwaysSpawn;

	AStaticMeshActor* Actor = World->SpawnActor<AStaticMeshActor>(
		AStaticMeshActor::StaticClass(), Location, FRotator::ZeroRotator, Params);

	if (Actor)
	{
		Actor->GetStaticMeshComponent()->SetStaticMesh(CubeMesh);
		Actor->SetActorScale3D(Scale);
		Actor->SetActorLabel(ActorLabel);  // editor-only; safe in Editor module
	}

	return Actor;
}

// ---------------------------------------------------------------------------
// GenerateRoom
// ---------------------------------------------------------------------------

void URoomGeneratorSubsystem::GenerateRoom(
	FVector Center, FVector SizeXY, float WallHeight, float WallThickness, FString RoomName)
{
	// /Engine/BasicShapes/Cube is 100 x 100 x 100 UU at scale (1,1,1).
	// => scale component = desired_dimension_UU / 100.
	constexpr float S = 100.f;

	const float HX = SizeXY.X * 0.5f;    // half interior width
	const float HY = SizeXY.Y * 0.5f;    // half interior depth
	const float HT = WallThickness * 0.5f;
	const float HH = WallHeight * 0.5f;

	// ── Floor (top face at Center.Z) ──────────────────────────────────────
	SpawnScaledCube(nullptr,
		Center + FVector(0.f, 0.f, -HT),
		FVector(SizeXY.X / S, SizeXY.Y / S, WallThickness / S),
		RoomName + TEXT("_Floor"));

	// ── Ceiling (bottom face at Center.Z + WallHeight) ────────────────────
	SpawnScaledCube(nullptr,
		Center + FVector(0.f, 0.f, WallHeight + HT),
		FVector(SizeXY.X / S, SizeXY.Y / S, WallThickness / S),
		RoomName + TEXT("_Ceiling"));

	// ── North wall (−Y face) ──────────────────────────────────────────────
	SpawnScaledCube(nullptr,
		Center + FVector(0.f, -(HY + HT), HH),
		FVector(SizeXY.X / S, WallThickness / S, WallHeight / S),
		RoomName + TEXT("_WallN"));

	// ── South wall (+Y face) ──────────────────────────────────────────────
	SpawnScaledCube(nullptr,
		Center + FVector(0.f, HY + HT, HH),
		FVector(SizeXY.X / S, WallThickness / S, WallHeight / S),
		RoomName + TEXT("_WallS"));

	// ── West wall (−X face) ───────────────────────────────────────────────
	SpawnScaledCube(nullptr,
		Center + FVector(-(HX + HT), 0.f, HH),
		FVector(WallThickness / S, SizeXY.Y / S, WallHeight / S),
		RoomName + TEXT("_WallW"));

	// ── East wall (+X face) ───────────────────────────────────────────────
	SpawnScaledCube(nullptr,
		Center + FVector(HX + HT, 0.f, HH),
		FVector(WallThickness / S, SizeXY.Y / S, WallHeight / S),
		RoomName + TEXT("_WallE"));
}

// ---------------------------------------------------------------------------
// GenerateCorridor
// ---------------------------------------------------------------------------

void URoomGeneratorSubsystem::GenerateCorridor(
	FVector Start, FVector End, float Width, float Height,
	float WallThickness, FString CorridorName)
{
	FVector Dir = End - Start;
	const float Length = Dir.Size();
	if (Length < 1.f) return;
	Dir /= Length;   // normalize to unit direction

	const FVector Center = (Start + End) * 0.5f;
	const FRotator Rot   = Dir.Rotation();   // aligns local-X with Dir
	const float HT       = WallThickness * 0.5f;
	const float HH       = Height * 0.5f;
	constexpr float S    = 100.f;

	// Side vector perpendicular to Dir in the XY plane.
	// After applying Rot, this coincides with the actor's local +Y axis.
	const FVector Side = FVector::CrossProduct(FVector::UpVector, Dir).GetSafeNormal();

	// ── Floor ─────────────────────────────────────────────────────────────
	// Scale: local-X = Length (along Dir), local-Y = Width, local-Z = thickness
	AActor* Floor = SpawnScaledCube(nullptr,
		Center + FVector(0.f, 0.f, -HT),
		FVector(Length / S, Width / S, WallThickness / S),
		CorridorName + TEXT("_Floor"));
	if (Floor) Floor->SetActorRotation(Rot);

	// ── Ceiling ───────────────────────────────────────────────────────────
	AActor* Ceiling = SpawnScaledCube(nullptr,
		Center + FVector(0.f, 0.f, Height + HT),
		FVector(Length / S, Width / S, WallThickness / S),
		CorridorName + TEXT("_Ceiling"));
	if (Ceiling) Ceiling->SetActorRotation(Rot);

	// ── Left wall (offset in +Side direction) ────────────────────────────
	// Scale: local-X = Length, local-Y = WallThickness, local-Z = Height
	AActor* WallL = SpawnScaledCube(nullptr,
		Center + Side * (Width * 0.5f + HT) + FVector(0.f, 0.f, HH),
		FVector(Length / S, WallThickness / S, Height / S),
		CorridorName + TEXT("_WallL"));
	if (WallL) WallL->SetActorRotation(Rot);

	// ── Right wall (offset in −Side direction) ───────────────────────────
	AActor* WallR = SpawnScaledCube(nullptr,
		Center - Side * (Width * 0.5f + HT) + FVector(0.f, 0.f, HH),
		FVector(Length / S, WallThickness / S, Height / S),
		CorridorName + TEXT("_WallR"));
	if (WallR) WallR->SetActorRotation(Rot);
}

// ---------------------------------------------------------------------------
// SimulateKeyPress
// ---------------------------------------------------------------------------

bool URoomGeneratorSubsystem::SimulateKeyPress(APlayerController* PC, FName KeyName)
{
	if (!PC)
	{
		UE_LOG(LogTemp, Error, TEXT("RoomGenerator::SimulateKeyPress - PC is null"));
		return false;
	}

	const FKey Key(KeyName);
	if (!Key.IsValid())
	{
		UE_LOG(LogTemp, Error,
			TEXT("RoomGenerator::SimulateKeyPress - invalid key name '%s'"), *KeyName.ToString());
		return false;
	}

	// Both Pressed and Released in the same call -- mirrors a real, quick key
	// tap. Sending only Pressed would leave the key considered "held" until
	// something else releases it, which could confuse any Tick-based logic
	// reading is_input_key_down() afterward.
	FInputKeyParams PressParams;
	PressParams.Key = Key;
	PressParams.Event = IE_Pressed;
	PC->InputKey(PressParams);

	FInputKeyParams ReleaseParams;
	ReleaseParams.Key = Key;
	ReleaseParams.Event = IE_Released;
	PC->InputKey(ReleaseParams);

	return true;
}
