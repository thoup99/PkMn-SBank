import {render,screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {beforeEach,expect,it,vi} from 'vitest';
import ESP32 from './ESP32';
const status={supported_host:true,esptool_available:true,release:'v0.47.0',image:'pokeldn-radio-s3.bin',devices:[{device:'/dev/ttyACM0',description:'Test board'}],job:null};
const reply=(value:unknown)=>Promise.resolve({ok:true,json:async()=>value} as Response);
beforeEach(()=>{
 vi.stubGlobal('crypto',{randomUUID:()=> '11111111-1111-4111-8111-111111111111'});
 vi.stubGlobal('fetch',vi.fn().mockImplementation(()=>reply(status)));
});
it('requires acknowledgement and starts the selected board only on explicit installation',async()=>{
 const user=userEvent.setup();
 vi.mocked(fetch).mockImplementation((url)=>String(url).endsWith('/flash')?reply({id:'job',status:'running',message:'Writing',logs:['Connecting'],release:status.release}):reply(status));
 render(<ESP32 demo={false}/>);
 await screen.findByRole('option',{name:'/dev/ttyACM0 · Test board'});
 const install=screen.getByRole('button',{name:'Install matching firmware'});
 expect(install).toBeDisabled();
 expect(vi.mocked(fetch).mock.calls.some(c=>String(c[0]).endsWith('/flash'))).toBe(false);
 await user.click(screen.getByRole('checkbox'));
 await user.click(install);
 expect(await screen.findByText('Installation: running')).toBeInTheDocument();
 expect(install).toBeDisabled();
 const call=vi.mocked(fetch).mock.calls.find(c=>String(c[0]).endsWith('/flash'));
 expect(JSON.parse(call?.[1]?.body as string)).toEqual({device:'/dev/ttyACM0',confirmed:true,request_id:'11111111-1111-4111-8111-111111111111'});
});
it('shows boot instructions, permission setup and a completed job log',async()=>{
 vi.mocked(fetch).mockImplementation(()=>reply({...status,job:{id:'job',status:'completed',message:'Written; test radio next',logs:['Hash verified'],release:status.release}}));
 render(<ESP32 demo={false}/>);
 expect(await screen.findByRole('status')).toHaveTextContent('test radio next');
 expect(screen.getByLabelText('Firmware installation log')).toHaveTextContent('Hash verified');
 expect(screen.getByText('BOOT')).toBeInTheDocument();
 expect(screen.getByText(/sudo usermod/)).toBeInTheDocument();
});
it('disables installation in demo mode and on unsupported hosts',async()=>{
 vi.mocked(fetch).mockImplementation(()=>reply({...status,supported_host:false}));
 render(<ESP32 demo={true}/>);
 expect(await screen.findByText(/Demo mode is read-only/)).toBeInTheDocument();
 expect(screen.getByRole('checkbox')).toBeDisabled();
 expect(screen.getByRole('button',{name:'Install matching firmware'})).toBeDisabled();
});
it('keeps failures visible and does not automatically retry',async()=>{
 vi.mocked(fetch).mockImplementation(()=>reply({...status,job:{id:'job',status:'failed',message:'Check USB/BOOT',logs:['Connection failed'],release:status.release}}));
 render(<ESP32 demo={false}/>);
 expect(await screen.findByRole('status')).toHaveTextContent('Check USB/BOOT');
 expect(vi.mocked(fetch).mock.calls.some(c=>String(c[0]).endsWith('/flash'))).toBe(false);
});
