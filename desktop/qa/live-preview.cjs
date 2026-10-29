// The project-owned preview suite is the single maintained live acceptance path.
if (!process.argv.includes('--live')) process.argv.push('--live');
require('./project-previews.cjs');
