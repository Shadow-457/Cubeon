package com.cubeon.client.lod.mixin;
import com.cubeon.client.lod.LodClient;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.world.level.ChunkPos;
import net.minecraft.core.BlockPos;
import net.minecraft.world.level.block.state.BlockState;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.*;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(ClientLevel.class)
public abstract class LodChunkMixin {
    @Inject(method = "onChunkLoaded", at = @At("TAIL"))
    private void cubeon$lodLoaded(ChunkPos pos, CallbackInfo ci) { LodClient.dirty(pos.x(), pos.z()); }
    @Inject(method = "setSectionDirtyWithNeighbors", at = @At("TAIL"))
    private void cubeon$lodLight(int x, int y, int z, CallbackInfo ci) { LodClient.dirty(x, z); }
    @Inject(method = "sendBlockUpdated", at = @At("TAIL"))
    private void cubeon$lodEdited(BlockPos pos, BlockState before, BlockState after, int flags, CallbackInfo ci) {
        LodClient.dirty(Math.floorDiv(pos.getX(), 16), Math.floorDiv(pos.getZ(), 16));
    }
}
