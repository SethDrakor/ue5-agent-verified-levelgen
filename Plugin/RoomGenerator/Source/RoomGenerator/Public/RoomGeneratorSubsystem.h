#pragma once

#include "CoreMinimal.h"
#include "EditorSubsystem.h"
#include "RoomGeneratorSubsystem.generated.h"

/**
 * Editor subsystem exposing room/corridor generation to Python and Blueprints.
 * All geometry is built from /Engine/BasicShapes/Cube scaled to the required
 * dimensions. SpawnScaledCube is the primitive; GenerateRoom and
 * GenerateCorridor are higher-level helpers that call it with computed params.
 */
UCLASS()
class ROOMGENERATOR_API URoomGeneratorSubsystem : public UEditorSubsystem
{
	GENERATED_BODY()

public:
	/**
	 * Spawns one AStaticMeshActor using /Engine/BasicShapes/Cube at the given
	 * Location, scaled to Scale (UU = scale * 100), labelled ActorLabel.
	 * WorldContext may be nullptr -- falls back to the editor world.
	 */
	UFUNCTION(BlueprintCallable, Category = "RoomGenerator")
	AActor* SpawnScaledCube(UObject* WorldContext, FVector Location, FVector Scale, FString ActorLabel);

	/**
	 * Generates floor + ceiling + 4 walls for a rectangular room.
	 * Center   – world-space centre of the room interior.
	 * SizeXY   – interior X and Y extents (Z is ignored).
	 * WallHeight  – interior wall height (Z extent).
	 * WallThickness – thickness applied to every surface.
	 * RoomName – prefix for actor labels (e.g. "Room1_Floor", "Room1_WallN"...).
	 */
	UFUNCTION(BlueprintCallable, Category = "RoomGenerator")
	void GenerateRoom(FVector Center, FVector SizeXY, float WallHeight, float WallThickness, FString RoomName);

	/**
	 * Generates a corridor (floor + ceiling + 2 side walls) between Start and End.
	 * The corridor is axis-aligned along the Start→End direction.
	 */
	UFUNCTION(BlueprintCallable, Category = "RoomGenerator")
	void GenerateCorridor(FVector Start, FVector End, float Width, float Height, float WallThickness, FString CorridorName);

	/**
	 * Simulates a real key press+release on a live PlayerController via the
	 * native APlayerController::InputKey() path -- NOT a Blueprint/Enhanced
	 * Input fake. Exists so Python-driven test tooling (playtest_agent.py)
	 * can trigger real gameplay interactions (BPI_Interact message call via
	 * the player's own line-trace input event, BP_LightSwitch's
	 * WasInputKeyJustPressed() poll in Tick) from a live PIE session --
	 * Python has no exposed API to inject key state directly (confirmed:
	 * APlayerController only exposes read-only input queries to Python --
	 * is_input_key_down, was_input_key_just_pressed -- nothing that writes
	 * key state).
	 * KeyName must match a valid FKey name (e.g. "E"). Returns false if PC
	 * is null or KeyName doesn't resolve to a valid FKey.
	 */
	UFUNCTION(BlueprintCallable, Category = "RoomGenerator|Testing")
	bool SimulateKeyPress(APlayerController* PC, FName KeyName);
};
