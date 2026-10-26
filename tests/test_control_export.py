"""Run with Blender --background --factory-startup --python tests/test_control_export.py [-- output_dir]."""
import bpy,importlib.util,sys,json,ast,tempfile,wave
from pathlib import Path
root=Path(__file__).resolve().parents[1]
out=Path(sys.argv[sys.argv.index('--')+1]) if '--' in sys.argv else Path(tempfile.mkdtemp(prefix='control-export-'))
out.mkdir(parents=True,exist_ok=True)
audio=out/'step-test.wav'
with wave.open(str(audio),'wb') as stream:
 stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(24000);stream.writeframes(b'\0\0'*2400)
spec=importlib.util.spec_from_file_location('control_export_test',root/'__init__.py',submodule_search_locations=[str(root)])
addon=importlib.util.module_from_spec(spec);sys.modules[spec.name]=addon;spec.loader.exec_module(addon)
r=sys.modules[spec.name+'.shipmate.qt_rheostat'];h=sys.modules[spec.name+'.shipmate.qt_hatch']
r.qml_rheostat_register();h.qml_hatch_register()
try:
 legacy=bpy.data.objects.new('Legacy',None);legacy['qml_type']='Qml.Rheostat'
 assert not legacy.qml_rheostat_sequential_mode and legacy.qml_rheostat_step_sound==''
 assert 'SpatialSound' not in '\n'.join(r.export_qml_rheostat(legacy,'legacy',1))
 assert 'sequentialMode:' not in '\n'.join(r.export_qml_rheostat(legacy,'legacy',1))
 old_hatch=bpy.data.objects.new('OldHatch',None);old_hatch['qml_type']='Qml.Hatch'
 assert old_hatch.qml_hatch_step_sound==''
 assert 'SpatialSound' not in '\n'.join(h.export_qml_hatch(old_hatch,'old_hatch',1))
 legacy.qml_rheostat_sequential_mode=True;assert legacy['sequentialMode']
 assert 'sequentialMode: true' in '\n'.join(r.export_qml_rheostat(legacy,'legacy',1))
 legacy.qml_rheostat_step_sound='qrc:/sounds/a"b.wav'
 quoted='\n'.join(r.export_qml_rheostat(legacy,'legacy',1));assert json.dumps(legacy['stepSound']) in quoted
 bpy.ops.object.add_qml_rheostat(sequentialMode=True,stepSound=audio.as_uri())
 obj=bpy.context.object;assert obj['sequentialMode'];assert obj['stepSound']
 obj['value']=(0.,3.,9.);obj['change_step']=(10.,0.,0.);obj['change_duration']=120
 rheostat='\n'.join(r.export_qml_rheostat(obj,'rheo',1))
 assert 'SpatialSound {' in rheostat and 'position: control_rheo.node ? control_rheo.node.scenePosition' in rheostat
 assert 'target: control_rheo.anim' in rheostat and 'function onRunningChanged' in rheostat
 bpy.ops.object.add_qml_hatch(stepSound=obj['stepSound']);obj=bpy.context.object
 obj['final_rotation']=(30.,0.,0.);obj['value_out']='console.log("hatch-output", isFinal)'
 hatch='\n'.join(h.export_qml_hatch(obj,'hatch',1))
 assert 'onIsFinalChanged: console.log' in hatch and 'onInProgressChanged' in hatch
 class FakeParent:rigid_body=True
 # A real rigid-body parent exercises the node-vs-parent sound placement path.
 mesh=bpy.data.meshes.new('Body');body=bpy.data.objects.new('Body',mesh);bpy.context.collection.objects.link(body)
 bpy.context.view_layer.objects.active=body;body.select_set(True);bpy.ops.rigidbody.object_add();obj.parent=body
 rigid='\n'.join(h.export_qml_hatch(obj,'rigid',1));assert 'node: parent.parent' in rigid
 assert 'position: control_rigid.node ? control_rigid.node.scenePosition' in rigid
 imports='import QtQuick\nimport QtQuick3D\nimport QtQuick3D.SpatialAudio\nimport LogicModule as LM\n'
 (out/'RheostatFixture.qml').write_text(imports+'Node {\n property alias control: control_rheo\n position: Qt.vector3d(40, 50, 60)\n Model {id:knob; source:"#Cube"; position:Qt.vector3d(3,4,5)\n'+rheostat+'\n}\n}')
 (out/'HatchFixture.qml').write_text(imports+'Node {\n property alias control: control_hatch\n position: Qt.vector3d(40,50,60)\n Model {source:"#Cube"; position:Qt.vector3d(3,4,5)\n'+hatch+'\n}\n}')
 for p in [root/'shipmate/qt_step_sound.py',root/'shipmate/qt_rheostat.py',root/'shipmate/qt_hatch.py',root/'__init__.py']:ast.parse(p.read_text())
 print('CONTROL_EXPORT_TESTS_OK')
finally:
 h.qml_hatch_unregister();r.qml_rheostat_unregister()
