package com.cubeon.forge;
import net.minecraft.launchwrapper.IClassTransformer;
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;

/** Exact 1.8.9 hooks, after Forge's deobfuscator; no player-angle writes. */
public final class CameraTransformer implements IClassTransformer, Opcodes {
    private static final String HOOK="com/cubeon/forge/RenderHooks";
    private static boolean method(MethodNode m,String mcp,String srg) { return m.name.equals(mcp)||m.name.equals(srg); }
    private static MethodInsnNode call(String name,String desc) { return new MethodInsnNode(INVOKESTATIC,HOOK,name,desc,false); }
    @Override public byte[] transform(String name,String transformed,byte[] bytes) {
        if(bytes==null || !(transformed.equals("net.minecraft.entity.Entity") || transformed.equals("net.minecraft.client.renderer.EntityRenderer")
                || transformed.equals("net.minecraft.client.model.ModelPlayer") || transformed.equals("net.minecraft.client.multiplayer.PlayerControllerMP"))) return bytes;
        ClassNode c=new ClassNode(); new ClassReader(bytes).accept(c,0); boolean changed=false;
        for(MethodNode m:c.methods) {
            if(transformed.equals("net.minecraft.entity.Entity") && method(m,"setAngles","func_70082_c") && m.desc.equals("(FF)V")) {
                InsnList head=new InsnList(); LabelNode vanilla=new LabelNode();
                head.add(new VarInsnNode(ALOAD,0)); head.add(new VarInsnNode(FLOAD,1)); head.add(new VarInsnNode(FLOAD,2));
                head.add(call("look","(Ljava/lang/Object;FF)Z")); head.add(new JumpInsnNode(IFEQ,vanilla)); head.add(new InsnNode(RETURN));
                head.add(vanilla); head.add(new FrameNode(F_SAME,0,null,0,null)); m.instructions.insert(head); changed=true;
            }
            if(transformed.equals("net.minecraft.client.renderer.EntityRenderer") && method(m,"orientCamera","func_78467_g")) {
                for(AbstractInsnNode n:m.instructions.toArray()) if(n instanceof FieldInsnNode && n.getOpcode()==GETFIELD) {
                    FieldInsnNode f=(FieldInsnNode)n; String hook=null;
                    if(f.name.equals("rotationYaw")||f.name.equals("field_70177_z")) hook="yaw";
                    if(f.name.equals("prevRotationYaw")||f.name.equals("field_70126_B")) hook="previousYaw";
                    if(f.name.equals("rotationPitch")||f.name.equals("field_70125_A")) hook="pitch";
                    if(f.name.equals("prevRotationPitch")||f.name.equals("field_70127_C")) hook="previousPitch";
                    if(hook!=null) { m.instructions.set(n,call(hook,"(Ljava/lang/Object;)F")); changed=true; }
                    else if(f.name.equals("thirdPersonDistance")||f.name.equals("thirdPersonDistanceTemp")||f.name.equals("field_78490_B")||f.name.equals("field_78491_C")) {
                        m.instructions.insert(n,call("distance","(F)F")); changed=true;
                    }
                }
            }
            if(transformed.equals("net.minecraft.client.model.ModelPlayer") && method(m,"setRotationAngles","func_78087_a")) {
                InsnList head=new InsnList(); head.add(new VarInsnNode(ALOAD,0)); head.add(call("restorePose","(Ljava/lang/Object;)V")); m.instructions.insert(head);
                for(AbstractInsnNode n:m.instructions.toArray()) if(n.getOpcode()==RETURN) {
                    InsnList tail=new InsnList(); tail.add(new VarInsnNode(ALOAD,0)); tail.add(new VarInsnNode(ALOAD,7)); tail.add(new VarInsnNode(FLOAD,3));
                    tail.add(call("pose","(Ljava/lang/Object;Ljava/lang/Object;F)V")); m.instructions.insertBefore(n,tail);
                }
                changed=true;
            }
            if(transformed.equals("net.minecraft.client.multiplayer.PlayerControllerMP") && method(m,"attackEntity","func_78764_a")) {
                InsnList head=new InsnList(); head.add(new VarInsnNode(ALOAD,2)); head.add(call("hit","(Ljava/lang/Object;)V")); m.instructions.insert(head); changed=true;
            }
            if(transformed.equals("net.minecraft.client.renderer.EntityRenderer") && method(m,"renderWorldPass","func_175068_a")) {
                for(AbstractInsnNode n:m.instructions.toArray()) if(n.getOpcode()==RETURN) {
                    InsnList tail=new InsnList(); tail.add(call("blur","()V")); m.instructions.insertBefore(n,tail);
                }
                changed=true;
            }
        }
        if(!changed) return bytes;
        ClassWriter writer=new ClassWriter(ClassWriter.COMPUTE_MAXS); c.accept(writer); return writer.toByteArray();
    }
}
