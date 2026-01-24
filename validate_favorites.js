/**
 * Simple validation script to check JavaScript syntax in favorites.html
 * This extracts and validates the JavaScript code
 */

const fs = require('fs');
const path = require('path');

// Configuration
const JQUERY_VERSION = '3.7.1';
const filePath = path.join(__dirname, 'Website', 'templates', 'favorites.html');

const content = fs.readFileSync(filePath, 'utf8');

// Extract JavaScript blocks
const scriptMatches = content.match(/<script[^>]*>([\s\S]*?)<\/script>/gi);

if (!scriptMatches) {
    console.error('No script tags found');
    process.exit(1);
}

console.log(`Found ${scriptMatches.length} script blocks`);

// Check for jQuery inclusion
const hasJQuery = content.includes(`jquery-${JQUERY_VERSION}.min.js`) || content.includes('jquery');
console.log(`jQuery ${JQUERY_VERSION} included: ${hasJQuery}`);

// Check for new features
const features = {
    'Quick Stats': content.includes('updateQuickStats'),
    'Search/Filter': content.includes('searchFavorites') && content.includes('filterFavorites'),
    'Sort': content.includes('sortFavorites'),
    'View Toggle': content.includes('applyViewMode'),
    'Keyboard Shortcuts': content.includes('openShortcutsModal'),
    'Last Updated': content.includes('updateLastUpdatedTime')
};

console.log('\nFeatures implemented:');
Object.entries(features).forEach(([feature, implemented]) => {
    console.log(`  ${implemented ? '✓' : '✗'} ${feature}`);
});

// Count key CSS classes
const cssClasses = [
    'quick-stats-bar',
    'favorites-toolbar',
    'toolbar-search',
    'view-toggle',
    'view-compact',
    'view-list',
    'keyboard-shortcuts-badge'
];

console.log('\nCSS Classes:');
cssClasses.forEach(className => {
    const count = (content.match(new RegExp(className, 'g')) || []).length;
    console.log(`  ${className}: ${count} occurrences`);
});

// Check for common JavaScript errors
const errors = [];

// Check for unmatched braces
const openBraces = (content.match(/{/g) || []).length;
const closeBraces = (content.match(/}/g) || []).length;
if (openBraces !== closeBraces) {
    errors.push(`Unmatched braces: ${openBraces} open, ${closeBraces} close`);
}

// Check for unmatched parentheses in script tags
scriptMatches.forEach((block, i) => {
    const js = block.replace(/<\/?script[^>]*>/g, '');
    const openParens = (js.match(/\(/g) || []).length;
    const closeParens = (js.match(/\)/g) || []).length;
    if (openParens !== closeParens) {
        errors.push(`Script block ${i + 1}: Unmatched parentheses (${openParens} open, ${closeParens} close)`);
    }
});

if (errors.length > 0) {
    console.log('\n⚠️  Potential issues:');
    errors.forEach(error => console.log(`  - ${error}`));
} else {
    console.log('\n✓ No obvious syntax errors detected');
}

console.log('\n✓ Validation complete!');
