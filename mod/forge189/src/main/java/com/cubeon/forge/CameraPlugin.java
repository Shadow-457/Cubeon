package com.cubeon.forge;
import net.minecraftforge.fml.relauncher.IFMLLoadingPlugin;
import java.util.Map;

@IFMLLoadingPlugin.Name("CubeonCameraAndEmotes")
@IFMLLoadingPlugin.MCVersion("1.8.9")
@IFMLLoadingPlugin.SortingIndex(1001)
@IFMLLoadingPlugin.TransformerExclusions({"com.cubeon.forge.CameraPlugin","com.cubeon.forge.CameraTransformer"})
public final class CameraPlugin implements IFMLLoadingPlugin {
    public String[] getASMTransformerClass() { return new String[]{"com.cubeon.forge.CameraTransformer"}; }
    public String getModContainerClass() { return null; }
    public String getSetupClass() { return null; }
    public void injectData(Map<String,Object> data) { }
    public String getAccessTransformerClass() { return null; }
}
