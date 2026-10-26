"""Blender integration regression for native Speaker export and audio resources."""
import bpy, importlib.util, sys, tempfile, wave, json, math
from pathlib import Path
from types import SimpleNamespace
root=Path(__file__).resolve().parents[1]
out=Path(sys.argv[sys.argv.index('--')+1]) if '--' in sys.argv else Path(tempfile.mkdtemp(prefix='speaker-export-'))
out.mkdir(parents=True,exist_ok=True)
spec=importlib.util.spec_from_file_location('speaker_export_test',root/'__init__.py',submodule_search_locations=[str(root)])
addon=importlib.util.module_from_spec(spec);sys.modules[spec.name]=addon;spec.loader.exec_module(addon)
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
path=out/'input.wav'
with wave.open(str(path),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(b'\0\0'*2400)
sound=bpy.data.sounds.load(str(path))
parent=bpy.data.objects.new('RotatedParent',None);bpy.context.collection.objects.link(parent)
parent.location=(10,20,30);parent.scale=(2,3,4);parent.rotation_euler=(0,0,math.radians(30))
data=bpy.data.speakers.new('SpeakerData');data.sound=sound;data.volume=.7;data.distance_reference=2;data.distance_max=20;data.attenuation=.5;data.volume_min=.1;data.volume_max=.9;data.cone_angle_inner=60;data.cone_angle_outer=120;data.cone_volume_outer=.2;data.pitch=1.2
speaker=bpy.data.objects.new('EngineSpeaker',data);bpy.context.collection.objects.link(speaker);speaker.parent=parent;speaker.location=(1,2,3);speaker.rotation_euler=(.2,.3,.4);speaker['autoPlay']=False;speaker['loops']=-1
child=bpy.data.objects.new('SpeakerChild',None);bpy.context.collection.objects.link(child);child.parent=speaker;child.location=(1,0,0)
# A shared speaker/audio datablock must not duplicate audio files.
copy=speaker.copy();copy.name='SecondSpeaker';copy.parent=None;bpy.context.collection.objects.link(copy)
hidden=speaker.copy();hidden.name='HiddenSpeaker';hidden.hide_render=True;hidden.parent=None;bpy.context.collection.objects.link(hidden)
reports=[]
settings=SimpleNamespace(report=lambda level,message:reports.append((level,message)),convert_coords=True,export_animations=False,export_lights=False,export_cameras=False,apply_modifiers=False,generate_lods=False)
bpy.context.view_layer.update();exporter=addon.BalsamExporter(str(out/'SpeakerScene.qml'),settings);assert exporter.export()=={'FINISHED'}
qml=(out/'SpeakerScene.qml').read_text();assert qml.count('SpatialSound {')==2,qml
assert 'HiddenSpeaker' not in qml and 'SpeakerChild' in qml
for token in ['property real maximumDistance: 20.0','property real referenceDistance: 2.0','property real rolloff: 0.5','property real coneInnerAngle: 60.0','property real coneOuterAngle: 120.0','autoPlay: false','loops: -1','property real blenderPitch:']:assert token in qml,token
assert len(exporter.exp_sounds)==1
relative=next(iter(exporter.exp_sounds.values()));assert (out/relative).read_bytes()==path.read_bytes()
assert relative in (out/'SpeakerScene.qrc').read_text() and relative in (out/'CMakeLists_qt3d_snippet.txt').read_text()
assert json.loads((out/'export_manifest.json').read_text())['sounds']==[relative]
assert any('pitch' in message for _,message in reports)
assert 'import QtQuick3D.SpatialAudio' in qml
# Packed sound remains exportable if its source file has been removed.
sound.pack();path.unlink();packed=addon.BalsamExporter(str(out/'PackedScene.qml'),settings);packed_source=packed._export_sound(sound);assert (out/packed_source).exists()
# Reusable collection exports need their own SpatialAudio import.
collection=bpy.data.collections.new('SpeakerCollection');collection.objects.link(copy)
bpy.context.collection.objects.unlink(copy)
instance=bpy.data.objects.new('Instance',None);instance.instance_type='COLLECTION';instance.instance_collection=collection;bpy.context.collection.objects.link(instance)
instance.location=(4,5,6)
instance_export=addon.BalsamExporter(str(out/'Instances.qml'),settings);instance_export.export()
assert instance_export.component_files
assert any('import QtQuick3D.SpatialAudio' in (out/name).read_text() and 'SpatialSound {' in (out/name).read_text() for name in instance_export.component_files)
# Qt resources are owned by the application: preserve URLs without touching files.
qrc_source = 'qrc:/Assets/Common/Sound/Old_Diesel1.wav'
sound.filepath = qrc_source
qrc_export = addon.BalsamExporter(str(out/'QrcScene.qml'), settings)
assert qrc_export._export_sound(qrc_source) == qrc_source
assert qrc_export._export_sound(sound) == qrc_source
assert not qrc_export.exp_sounds
assert qrc_export.export() == {'FINISHED'}
qrc_qml = (out/'QrcScene.qml').read_text()
qrc_components = [(out/name).read_text() for name in qrc_export.component_files]
assert any('source: "' + qrc_source + '"' in text for text in [qrc_qml] + qrc_components)
assert not qrc_export.exp_sounds
assert not any('Cannot export speaker sound' in message for _, message in reports)
# Controller is a QML expression, not a quoted string. Test the generated scene.
speaker['controller'] = 'root.engineController'
speaker['autoPlay'] = True
controlled = addon.BalsamExporter(str(out/'ControlledScene.qml'), settings)
assert controlled.export() == {'FINISHED'}
controlled_qml = (out/'ControlledScene.qml').read_text()
for token in ['property var controller: root.engineController', 'function onSoundChanged()',
              'const shouldPlay = !!(state && state.play)', 'Number(state.volume)',
              'Component.onCompleted: syncControllerSound()', 'autoPlay: false',
              'distanceModel: SpatialSound.Logarithmic', 'function onPlayChanged()',
              'function onVolumeChanged()']:
    assert token in controlled_qml, token
assert 'ManualAttenuation' not in controlled_qml
assert 'attenuationAt' not in controlled_qml
print('SPEAKER_EXPORT_TESTS_OK')
