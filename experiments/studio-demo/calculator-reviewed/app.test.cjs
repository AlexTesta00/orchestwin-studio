const test = require('node:test');
const assert = require('node:assert/strict');
const { calculate, readNumber, formatResult, calculationSummary } = require('./app.js');

for (const [name, a, b, operation, expected] of [
  ['addition', '5', '3', '+', 8], ['subtraction', '10', '12', '−', -2],
  ['multiplication', '4', '2', '×', 8], ['division', '6', '2', '÷', 3],
  ['zero input', '0', '7', '+', 7], ['negative', '-3', '2', '×', -6],
  ['decimal comma', '1,5', '2.25', '+', 3.75], ['leading decimal', '.5', ',25', '+', .75],
]) test(name, () => assert.equal(calculate(a, b, operation), expected));
test('division by zero is rejected', () => assert.throws(() => calculate('5', '-0', '÷'), /zero/));
test('blank, partial numbers and non-finite input are rejected', () => {
  for (const input of ['', ' ', '3abc', 'Infinity', 'NaN', '1,2,3', '1e309']) assert.throws(() => readNumber(input));
});
test('unknown operation is rejected', () => assert.throws(() => calculate('1', '2', '?')));
test('common floating-point noise is not displayed', () => assert.equal(formatResult(calculate('0.1', '0.2', '+')), '0,3'));
test('negative zero is normalized', () => assert.equal(Object.is(calculate('-0', '2', '×'), -0), false));
for (const [operation, expected] of [
  ['Addizione', '9 + 3 = 12'], ['Sottrazione', '9 − 3 = 6'],
  ['Moltiplicazione', '9 × 3 = 27'], ['Divisione', '9 ÷ 3 = 3'],
]) test(`mockup operation ${operation} produces the actual expression`, () => {
  assert.equal(calculationSummary('9', '3', operation), expected);
});
test('result screen uses current decimal operands rather than the mockup example', () => {
  assert.equal(calculationSummary('1,5', '2.25', 'Addizione'), '1,5 + 2,25 = 3,75');
});
test('the mockup operation must be explicitly selected', () => {
  assert.throws(() => calculationSummary('5', '3', ''), /Seleziona/);
});
test('the result screen cannot be populated after a division by zero', () => {
  assert.throws(() => calculationSummary('5', '0', 'Divisione'), /zero/);
});
