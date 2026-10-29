import {render,screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {expect,it,vi} from 'vitest';
import KeysSettings from './KeysSettings';
it('uploads a file and displays installation status without its contents',async()=>{
 const fetcher=vi.fn().mockImplementation((_url,options)=>Promise.resolve({ok:true,json:async()=>({installed:options?.method==='PUT'})}));
 vi.stubGlobal('fetch',fetcher);
 render(<KeysSettings/>);
 await screen.findByText('Keys not uploaded');
 const file=new File(['synthetic secret'], 'prod.keys');
 await userEvent.upload(screen.getByLabelText('prod.keys file'),file);
 expect(await screen.findByText('Keys are present')).toBeInTheDocument();
 const upload=fetcher.mock.calls.find(call=>call[1]?.method==='PUT');
 expect(upload?.[1].body).toBe(file);
 expect(screen.queryByText('synthetic secret')).not.toBeInTheDocument();
});
it('shows an upload failure and clears the file selection',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockImplementation((_url,options)=>Promise.resolve({ok:!options?.method,json:async()=>options?.method?{detail:'Invalid keys; previous file kept.'}:{installed:true}})));
 render(<KeysSettings/>);
 await screen.findByText('Keys are present');
 const input=screen.getByLabelText('prod.keys file') as HTMLInputElement;
 await userEvent.upload(input,new File(['invalid'],'prod.keys'));
 expect(await screen.findByRole('alert')).toHaveTextContent('previous file kept');
 expect(input.value).toBe('');
 expect(screen.getByText('Keys are present')).toBeInTheDocument();
});

it('opens the native file prompt from the visible upload button', async () => {
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({installed:false})}));
 render(<KeysSettings/>);
 const input=screen.getByLabelText('prod.keys file') as HTMLInputElement;
 const openPicker=vi.spyOn(input,'click');
 const button=screen.getByRole('button',{name:'Upload prod.keys'});
 expect(button).toBeVisible();
 await userEvent.click(button);
 expect(openPicker).toHaveBeenCalledOnce();
 expect(await screen.findByRole('status')).toHaveTextContent('Keys not uploaded');
});
