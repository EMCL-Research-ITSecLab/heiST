import {createContext, useContext, useEffect, useState, type ReactNode} from 'react';
import {translate, type Language, type Values} from './translation.ts';
const I18n=createContext({language:'en' as Language,setLanguage: (_:Language)=>{},t:(message:string,_values:Values={})=>message});
export function LanguageProvider({children}:{children:ReactNode}) {
  const [language,setLanguage]=useState<Language>(()=>{
    try { const saved=localStorage.getItem('heist-language'); if(saved==='de'||saved==='en')return saved; } catch {}
    return navigator.language.toLowerCase().startsWith('de')?'de':'en';
  });
  useEffect(()=>{document.documentElement.lang=language;try{localStorage.setItem('heist-language',language);}catch{}},[language]);
  return <I18n.Provider value={{language,setLanguage,t:(message,values)=>translate(language,message,values)}}>{children}</I18n.Provider>;
}
export const useI18n=()=>useContext(I18n);
