import { blake2b } from './blake2b.js';
import { ml_dsa44 } from './ml-dsa.js';
const seed = new Uint8Array(32);
const { publicKey } = ml_dsa44.keygen(seed);
console.log("  blake2b ok:", typeof blake2b === 'function', "| ml_dsa44.keygen ok:", publicKey.length === 1312);
