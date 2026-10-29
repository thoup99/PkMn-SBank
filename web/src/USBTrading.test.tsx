import {render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {beforeEach,expect,it,vi} from 'vitest';
import USBTrading, {newRequestId} from './USBTrading';
import type {Box} from './types';
const boxes:Box[]=[{id:5,kind:'dummy',name:'Pikachu reserve',slots:[{id:'dummy-pikachu-01',species:'Pikachu',dex:25,level:null,types:['Electric'],nature:null,ability:null,game:'Reusable deposit offer',trainer:null,shiny:false,dummy:true},...Array(29).fill(null)]}];
const status={supported_host:true,keys_available:true,devices:[{device:'/dev/ttyACM0',description:'Espressif USB'}],games:[{key:'swsh',name:'Sword / Shield',available:true},{key:'sv',name:'Scarlet / Violet',available:false}],session:null,logs:[]};
const session={id:'abc',status:'running',message:'Waiting for console',code:'12345678',species:'Pikachu',received_id:null};
const reply=(data:unknown)=>Promise.resolve({ok:true,json:async()=>data} as Response);
beforeEach(()=>{vi.stubGlobal('crypto',{randomUUID:()=> '11111111-1111-4111-8111-111111111111'});vi.stubGlobal('fetch',vi.fn().mockImplementation(()=>reply(status)));});
it('starts only an explicitly requested real USB trade with the selected reserve offer',async()=>{
 let active=false;const user=userEvent.setup();
 vi.mocked(fetch).mockImplementation(input=>{if(String(input).endsWith('/start')){active=true;return reply(session);}return reply({...status,session:active?session:null});});
 render(<USBTrading boxes={boxes} onChange={vi.fn()}/>);
 await screen.findByRole('option',{name:'/dev/ttyACM0 · Espressif USB'});
 expect(screen.getByRole('button',{name:'Start real Sword/Shield trade'})).toBeDisabled();
 await user.selectOptions(screen.getByRole('combobox',{name:'Destination game'}),'swsh');
 await user.click(screen.getByRole('button',{name:'Start real Sword/Shield trade'}));
 expect(await screen.findByRole('button',{name:'Stop USB trade'})).toBeInTheDocument();
 const call=vi.mocked(fetch).mock.calls.find(c=>String(c[0]).endsWith('/start'));
 expect(JSON.parse(call?.[1]?.body as string)).toEqual({game:'swsh',entry_id:'dummy-pikachu-01',device:'/dev/ttyACM0',code:'12345678',request_id:'11111111-1111-4111-8111-111111111111'});
 expect(screen.getByRole('button',{name:'Start real Sword/Shield trade'})).toBeDisabled();
});
it('requires operator acknowledgement before resolving an unconfirmed result',async()=>{
 const user=userEvent.setup();vi.mocked(fetch).mockImplementation(()=>reply({...status,session:{...session,status:'uncertain'}}));
 render(<USBTrading boxes={boxes} onChange={vi.fn()}/>);
 const resolve=await screen.findByRole('button',{name:'Resolve unconfirmed session'});expect(resolve).toBeDisabled();
 await user.click(screen.getByRole('checkbox'));expect(resolve).toBeEnabled();await user.click(resolve);
 const call=vi.mocked(fetch).mock.calls.find(c=>String(c[0]).endsWith('/recover'));
 expect(JSON.parse(call?.[1]?.body as string).resolve_without_confirmation).toBe(true);
});
it('keeps the real start control disabled without a supported Pi and keys',async()=>{
 vi.mocked(fetch).mockImplementation(()=>reply({...status,supported_host:false,keys_available:false}));
 render(<USBTrading boxes={boxes} onChange={vi.fn()}/>);
 expect(await screen.findByText(/requires the Raspberry Pi 5 server/)).toBeInTheDocument();
 expect(screen.getByRole('button',{name:'Start real Sword/Shield trade'})).toBeDisabled();
});

it('creates request IDs on plain HTTP Pi LAN pages without randomUUID',()=>{
 vi.stubGlobal('crypto',{getRandomValues:(bytes:Uint8Array)=>{bytes.fill(3);return bytes;}});
 expect(newRequestId()).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
});

it('shows unavailable live destinations without permitting their selection',async()=>{
 const user=userEvent.setup();
 render(<USBTrading boxes={boxes} onChange={vi.fn()}/>);
 const unsupported=await screen.findByRole('option',{name:'Scarlet / Violet — live trading not connected yet'});
 expect(unsupported).toBeDisabled();
 const select=screen.getByRole('combobox',{name:'Destination game'});
 await user.selectOptions(select,'sv');
 expect(select).toHaveValue('');
 expect(screen.getByRole('button',{name:'Start real Sword/Shield trade'})).toBeDisabled();
 expect(vi.mocked(fetch).mock.calls.some(call=>String(call[0]).endsWith('/start'))).toBe(false);
});
