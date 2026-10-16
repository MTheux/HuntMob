// Narrow CoreSimulator adapter: owned UDID and fixed operations only.
import {NativeSimctl} from '@appium/coresim';
const [udid, action, value] = process.argv.slice(2);
if (!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(udid ?? '')) throw new Error('Invalid Simulator UUID');
const simulator = new NativeSimctl();
try {
  if (action === 'rotation') {
    const orientation = {portrait:1,landscape:4}[value];
    if (!orientation) throw new Error('Invalid orientation');
    await simulator.setOrientation(udid,orientation);
    let observed=await simulator.getOrientation(udid);
    for(let attempt=0;attempt<10 && observed!==orientation;attempt++) {
      await new Promise(resolve=>setTimeout(resolve,100));
      observed=await simulator.getOrientation(udid);
    }
    console.log(JSON.stringify({ok:true,requested_orientation:orientation,orientation:observed,readback_matches:observed===orientation}));
  } else throw new Error('Unsupported operation');
} catch (error) {
  console.log(JSON.stringify({ok:false,error_type:error.name,reason:'CoreSimulator recusou a operação.'}));
  process.exitCode=1;
}
