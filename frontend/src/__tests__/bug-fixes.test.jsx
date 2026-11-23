/**
 * Regression tests for frontend bug fixes from PR #9.
 *
 * Bugs covered:
 *   9.  Temporal dead zone in App.jsx (handleLogout referenced before declaration)
 *  10.  Stale closure in useEffect (captured initial token instead of reading localStorage)
 *  11.  Unstable callbacks (fetchMemories recreated every render, missing useCallback)
 *  12.  JWT leaked in URL (graph link had ?token=...)
 *  13.  Duplicate CSS reset (* selector in both index.css and App.css)
 *
 * Additional frontend bugs:
 *  17.  Unused catch parameters (catch(e) where e is never used)
 *  16.  Unused react-router-dom dependency
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { readFileSync } from 'fs'
import { join } from 'path'
import React from 'react'


// ---------------------------------------------------------------------------
// Bug 9: Temporal dead zone in App.jsx
// handleLogout was referenced in useEffect dependency array before its
// const declaration. The fix reorders declarations and uses useCallback.
// ---------------------------------------------------------------------------
describe('Bug 9: Temporal dead zone in App.jsx', () => {
  it('App.jsx should import useCallback from React', () => {
    const source = readFileSync(join(__dirname, '..', 'App.jsx'), 'utf-8')
    expect(source).toContain('useCallback')
    // useCallback must be imported
    const importLine = source.split('\n').find(l => l.includes('import') && l.includes('react'))
    expect(importLine).toContain('useCallback')
  })

  it('handleLogout should be declared before the useEffect that uses it', () => {
    const source = readFileSync(join(__dirname, '..', 'App.jsx'), 'utf-8')
    const lines = source.split('\n')

    // Find the line where handleLogout is declared
    const handleLogoutDeclLine = lines.findIndex(l =>
      l.includes('handleLogout') && (l.includes('const') || l.includes('function'))
    )

    // Find the first useEffect that references handleLogout
    const useEffectWithLogout = lines.findIndex(l =>
      l.includes('useEffect') && lines.slice(l).some(sl => sl.includes('handleLogout'))
    )

    // handleLogout declaration must come BEFORE the useEffect
    expect(handleLogoutDeclLine).toBeGreaterThan(-1)
    expect(handleLogoutDeclLine).toBeLessThan(
      lines.findIndex((l, i) => i > handleLogoutDeclLine && l.includes('useEffect'))
    )
  })

  it('handleLogout should be wrapped in useCallback', () => {
    const source = readFileSync(join(__dirname, '..', 'App.jsx'), 'utf-8')
    // The fixed version wraps handleLogout in useCallback
    expect(source).toMatch(/handleLogout\s*=\s*useCallback/)
  })
})


// ---------------------------------------------------------------------------
// Bug 10: Stale closure in useEffect
// The mount effect captured the initial `token` state value, which could
// be stale. The fix reads directly from localStorage.
// ---------------------------------------------------------------------------
describe('Bug 10: Stale closure in useEffect', () => {
  it('mount useEffect should read token from localStorage, not from state', () => {
    const source = readFileSync(join(__dirname, '..', 'App.jsx'), 'utf-8')

    // Extract the useEffect block that does auth verification
    // The fixed code uses localStorage.getItem("zen_token") inside the effect
    const effectMatch = source.match(/useEffect\(\(\)\s*=>\s*\{[\s\S]*?auth\/me[\s\S]*?\}\s*,\s*\[/)
    expect(effectMatch).not.toBeNull()

    const effectBody = effectMatch[0]
    // Should read from localStorage inside the effect
    expect(effectBody).toContain('localStorage.getItem')
    expect(effectBody).toContain('savedToken')
  })

  it('should use savedToken variable (from localStorage) for API calls in mount effect', () => {
    const source = readFileSync(join(__dirname, '..', 'App.jsx'), 'utf-8')
    // The fixed code creates a local savedToken and uses it for fetch calls
    const effectMatch = source.match(/useEffect\(\(\)\s*=>\s*\{[\s\S]*?auth\/me[\s\S]*?\}\s*,\s*\[/)
    expect(effectMatch).not.toBeNull()

    const effectBody = effectMatch[0]
    // The fetch calls inside should use savedToken, not the state `token`
    const fetchCalls = effectBody.match(/Bearer \$\{(\w+)\}/g) || []
    for (const call of fetchCalls) {
      expect(call).toContain('savedToken')
    }
  })
})


// ---------------------------------------------------------------------------
// Bug 11: Unstable callbacks
// fetchMemories was recreated on every render, causing unnecessary
// re-renders and potential stale closures. The fix wraps it in useCallback.
// ---------------------------------------------------------------------------
describe('Bug 11: Unstable callbacks (fetchMemories)', () => {
  it('fetchMemories should be wrapped in useCallback', () => {
    const source = readFileSync(join(__dirname, '..', 'App.jsx'), 'utf-8')
    expect(source).toMatch(/fetchMemories\s*=\s*useCallback/)
  })

  it('fetchMemories useCallback should have proper dependencies', () => {
    const source = readFileSync(join(__dirname, '..', 'App.jsx'), 'utf-8')
    // Find the useCallback for fetchMemories and check its deps
    const match = source.match(/fetchMemories\s*=\s*useCallback\([\s\S]*?\}\s*,\s*\[([^\]]*)\]/)
    expect(match).not.toBeNull()
    const deps = match[1]
    expect(deps).toContain('token')
    expect(deps).toContain('handleLogout')
  })

  it('useEffect watching token should include fetchMemories in deps', () => {
    const source = readFileSync(join(__dirname, '..', 'App.jsx'), 'utf-8')
    // The useEffect that calls fetchMemories when token changes
    // should have fetchMemories in its dependency array
    const match = source.match(/useEffect\(\(\)\s*=>\s*\{\s*\n?\s*if\s*\(token\)\s*fetchMemories/)
    expect(match).not.toBeNull()

    // Find the dependency array for this specific useEffect
    const afterMatch = source.slice(source.indexOf(match[0]))
    const depsMatch = afterMatch.match(/\}\s*,\s*\[([^\]]*)\]\s*\)/)
    expect(depsMatch).not.toBeNull()
    expect(depsMatch[1]).toContain('fetchMemories')
  })
})


// ---------------------------------------------------------------------------
// Bug 12: JWT leaked in URL
// The graph link in ChatView.jsx appended ?token=... to the URL.
// The fix removes the token query parameter.
// ---------------------------------------------------------------------------
describe('Bug 12: JWT leaked in URL (ChatView.jsx)', () => {
  it('graph link should NOT contain token query parameter', () => {
    const source = readFileSync(
      join(__dirname, '..', 'components', 'ChatView.jsx'),
      'utf-8'
    )
    expect(source).not.toContain('?token=')
    expect(source).not.toContain('token=${')
    expect(source).not.toContain('token=\\${')
  })

  it('graph link href should be a plain URL without query params', () => {
    const source = readFileSync(
      join(__dirname, '..', 'components', 'ChatView.jsx'),
      'utf-8'
    )
    // Find the href for the graph link
    const hrefMatch = source.match(/href\s*=\s*["'`]([^"'`]*graph[^"'`]*)["'`]/)
      || source.match(/href\s*=\s*\{[^}]*graph[^}]*\}/)
    expect(hrefMatch).not.toBeNull()

    // The href should be a simple URL without query parameters
    const href = hrefMatch[1] || hrefMatch[0]
    expect(href).not.toContain('?')
    expect(href).not.toContain('token')
  })
})


// ---------------------------------------------------------------------------
// Bug 13: Duplicate CSS reset
// The universal * reset was declared in both index.css and App.css.
// The fix removes it from index.css (keeping it only in App.css).
// ---------------------------------------------------------------------------
describe('Bug 13: Duplicate CSS reset', () => {
  it('index.css should NOT contain a universal * reset', () => {
    const source = readFileSync(join(__dirname, '..', 'index.css'), 'utf-8')
    // The fixed index.css should not have the * { margin: 0; padding: 0; ... } block
    const hasUniversalReset = /\*\s*\{[^}]*(margin|padding)\s*:\s*0/.test(source)
    expect(hasUniversalReset).toBe(false)
  })

  it('App.css should still contain the universal * reset', () => {
    const source = readFileSync(join(__dirname, '..', 'App.css'), 'utf-8')
    // App.css should keep the reset
    expect(source).toMatch(/\*\s*\{/)
    expect(source).toContain('margin: 0')
    expect(source).toContain('padding: 0')
    expect(source).toContain('box-sizing: border-box')
  })

  it('the * reset should appear in exactly one CSS file', () => {
    const indexCss = readFileSync(join(__dirname, '..', 'index.css'), 'utf-8')
    const appCss = readFileSync(join(__dirname, '..', 'App.css'), 'utf-8')

    const indexHasReset = /\*\s*\{[^}]*(margin|padding)\s*:\s*0/.test(indexCss)
    const appHasReset = /\*\s*\{[^}]*(margin|padding)\s*:\s*0/.test(appCss)

    // Exactly one should have it
    expect(indexHasReset).toBe(false)
    expect(appHasReset).toBe(true)
  })
})


// ---------------------------------------------------------------------------
// Bug 17: Unused catch parameters
// catch(e) where e is never used should be bare catch.
// ---------------------------------------------------------------------------
describe('Bug 17: Unused catch parameters', () => {
  it('App.jsx sendMessage catch should not have unused parameter', () => {
    const source = readFileSync(join(__dirname, '..', 'App.jsx'), 'utf-8')
    // Find catch blocks in sendMessage context
    // The fixed code uses bare `catch {` instead of `catch (e) {`
    // Look for the sendMessage function's catch block
    const sendMsgSection = source.slice(
      source.indexOf('sendMessage'),
      source.indexOf('deleteMemory')
    )
    // Should not have catch(e) or catch (e) where e is unused
    const catchBlocks = sendMsgSection.match(/catch\s*\(\s*\w+\s*\)\s*\{/g) || []
    // The main catch in sendMessage should be bare (no parameter)
    // There might be other catches with used params, so check specifically
    // for the "Something went wrong" catch
    const wrongCatch = sendMsgSection.match(/catch\s*(\([^)]*\))?\s*\{[^}]*Something went wrong/)
    if (wrongCatch) {
      // If there's a parameter, it should be absent (bare catch)
      expect(wrongCatch[1]).toBeUndefined()
    }
  })

  it('AuthPage.jsx catch should not have unused parameter', () => {
    const source = readFileSync(
      join(__dirname, '..', 'components', 'AuthPage.jsx'),
      'utf-8'
    )
    // Find the catch block that sets "Cannot connect to server"
    const catchMatch = source.match(/catch\s*(\([^)]*\))?\s*\{[^}]*Cannot connect/)
    expect(catchMatch).not.toBeNull()
    // The parameter should be absent (bare catch)
    expect(catchMatch[1]).toBeUndefined()
  })
})


// ---------------------------------------------------------------------------
// Bug 16: Unused react-router-dom dependency
// react-router-dom was in package.json but never imported.
// ---------------------------------------------------------------------------
describe('Bug 16: Unused react-router-dom dependency', () => {
  it('package.json should not list react-router-dom', () => {
    const pkg = JSON.parse(
      readFileSync(join(__dirname, '..', '..', 'package.json'), 'utf-8')
    )
    const allDeps = {
      ...(pkg.dependencies || {}),
      ...(pkg.devDependencies || {}),
    }
    expect(allDeps).not.toHaveProperty('react-router-dom')
  })
})
