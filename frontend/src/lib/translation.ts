import {german} from './messages/de.ts';
export type Language='en'|'de';
export type Values=Record<string,string|number>;

/** Interpolation returns plain text. Unknown messages retain the English source. */
export function translate(language:Language,message:string,values:Values={}):string {
  const key=message.trim(),translated=language==='de'&&Object.hasOwn(german,key)?german[key]:undefined;
  const output=translated===undefined?message:message.slice(0,message.indexOf(key))+translated+message.slice(message.indexOf(key)+key.length);
  return output.replace(/\{([a-zA-Z_]+)\}/g,(placeholder,name)=>Object.hasOwn(values,name)?String(values[name]):placeholder);
}
