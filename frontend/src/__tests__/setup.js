import '@testing-library/jest-dom'

// jsdom does not implement scrollIntoView — stub it for component tests
if (typeof Element !== 'undefined') {
  Element.prototype.scrollIntoView = Element.prototype.scrollIntoView || function () {}
}
