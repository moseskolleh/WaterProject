
  /* ============================================================ other languages
   * groundwater/text.py, "Other languages" (PLAN.md step 9.2). English is
   * the working language and GWT.data.text is the English. A translation is
   * a folder beside the English files named for the language
   * (src/groundwater/data/text/kri), which the build emits here as
   * GWT.data.translations[code] = {language, text}: the facts of its
   * language.yaml, and as many entries of each file as are translated.
   *
   * The rules are text.py's, rule for rule, and the parity suite holds the
   * two to each other on translations made up for the purpose: an entry not
   * translated (left out, or named with nothing after it) is said in English
   * and counted; a translation is offered only if it says what it is, who
   * translated it and who checked it, every file of it could be read, and
   * it has no entry English lacks, no sentence that takes other values than
   * the English one or writes one another way, no table row English lacks
   * and nothing blank. Only what a community reads is said through a
   * speaker; reports and notes to whoever builds a document stay in
   * English. */

  /** @typedef {{code: string, language: Rec, fellBack: string[],
   *   phrase: function(string, Record<string, *>=): string,
   *   phraseTable: function(string): Record<string, *>,
   *   row: function(string, string): string}} Speaker */

  var LANGUAGE_FACTS = ['name', 'translated_by', 'checked_by'];
  var LANGUAGE_CODE = /^[a-z]{2,8}$/;
  /* how what the build keeps for a file it could not read begins (text.py
   * UNREADABLE) */
  var UNREADABLE = 'cannot be read';
  /* The white space taken off the ends of a sentence, a row and a fact, and
   * what makes one blank (text.py _EDGE). Written out, and the same list
   * there: trim() and Python's strip() do not take the same characters, and
   * a translation one app offered and the other refused would follow. This
   * is every character either takes. */
  var EDGE = '[\\t\\n\\v\\f\\r \\x1c-\\x1f\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029' +
    '\\u202f\\u205f\\u3000\\ufeff]';
  var EDGES = new RegExp('^' + EDGE + '+|' + EDGE + '+$', 'g');
  /* written out rather than \s, which the two engines read differently */
  var TEXT_SPACES = /[ \t\n\r\f\v]+/g;

  /** @param {string} value
   * @returns {string} */
  function textTrimmed(value) {
    return value.replace(EDGES, '');
  }

  /** Translated text as it is printed (text.py _tidy): a long dash as a
   * hyphen with spaces and a short one as a hyphen, each run of spaces one
   * space, the ends trimmed, so that the two document writers are handed
   * text neither has cause to change.
   * @param {string} text
   * @returns {string} */
  function textTidy(text) {
    return textTrimmed(text.replace(/—/g, ' - ').replace(/–/g, '-')
      .replace(TEXT_SPACES, ' '));
  }

  /** Every translation the build carries, by language code.
   * @returns {Record<string, Rec>} */
  function translations() {
    return (GWT.data || {}).translations || {};
  }

  /** Each value a template takes, with the formats it writes it in; null
   * where the template does not parse (a lone brace).
   * @param {string} template
   * @returns {Record<string, Record<string, boolean>>|null} */
  function textPlaceholders(template) {
    /* with no prototype: a value may be named __proto__, and on a plain
     * object that name is not a key */
    /** @type {Record<string, Record<string, boolean>>} */
    var taken = Object.create(null);
    var broken = false;
    TEXT_TOKEN.lastIndex = 0;
    template.replace(TEXT_TOKEN, function (token, name, spec) {
      if (token === '{{' || token === '}}') return token;
      if (name === undefined) { broken = true; return token; }
      /* the two words of a plural are the translation's own to choose */
      var format = spec === undefined ? '' : (spec.indexOf('plural:') === 0 ? 'plural' : spec);
      if (!own(taken, name)) taken[name] = Object.create(null);
      taken[name][format] = true;
      return token;
    });
    return broken ? null : taken;
  }

  /** Whether a translated sentence takes the values the English one takes,
   * each written as the English writes it (text.py _same_values). The value
   * itself is printed every way the English prints it and no other: a
   * sentence that kept the word "jerrycans" and lost their number would
   * pass a looser rule. Only the word that agrees with a count may be left
   * out, and it may not be added where English has none.
   * @param {Record<string, Record<string, boolean>>} mine
   * @param {Record<string, Record<string, boolean>>} theirs
   * @returns {boolean} */
  function sameValues(mine, theirs) {
    /** @param {Record<string, boolean>} formats */
    function printed(formats) {
      return Object.keys(formats).filter(function (f) { return f !== 'plural'; }).sort().join('\n');
    }
    if (Object.keys(mine).sort().join('\n') !== Object.keys(theirs).sort().join('\n')) return false;
    return Object.keys(theirs).every(function (name) {
      return printed(mine[name]) === printed(theirs[name]) &&
        (!own(mine[name], 'plural') || own(theirs[name], 'plural'));
    });
  }

  /** @param {*} value */
  function isPlainObject(value) {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
  }

  /** @param {*} value */
  function isUnreadable(value) {
    return typeof value === 'string' && value.indexOf(UNREADABLE) === 0;
  }

  /** Every reason the translation cannot be offered, in words; an empty
   * list where it can (text.py translation_problems).
   * @param {string} code
   * @param {Record<string, Rec>} [held] the translations to read
   * @param {Record<string, Rec>} [english] the catalogue they translate
   * @returns {string[]} */
  function translationProblems(code, held, english) {
    var all = held || translations();
    var source = english || (GWT.data || {}).text || {};
    if (!own(all, code)) return ['there is no translation ' + pyRepr(code)];
    var entry = all[code];
    var facts = entry.language || {};
    /** @type {string[]} */
    var problems = LANGUAGE_CODE.test(code) ? []
      : [pyRepr(code) + " is not a language's code (two to eight small letters)"];
    if (isUnreadable(facts)) {
      problems.push('language.yaml ' + facts);
    } else {
      LANGUAGE_FACTS.forEach(function (fact) {
        if (!(isPlainObject(facts) && typeof facts[fact] === 'string' && textTrimmed(facts[fact]))) {
          problems.push('language.yaml does not say ' + fact);
        }
      });
    }
    Object.keys(entry.text || {}).sort().forEach(function (namespace) {
      var entries = entry.text[namespace];
      if (!own(source, namespace)) {
        problems.push(namespace + '.yaml translates a file English does not have');
        return;
      }
      /* a file with nothing in it yet */
      if (entries === null) return;
      if (isUnreadable(entries)) {
        problems.push(namespace + '.yaml ' + entries);
        return;
      }
      if (!isPlainObject(entries)) {
        problems.push(namespace + '.yaml is not a list of entries');
        return;
      }
      Object.keys(entries).sort().forEach(function (key) {
        var ident = namespace + '.' + key, value = entries[key];
        var from = own(source[namespace], key) ? source[namespace][key] : null;
        if (from === null) {
          problems.push(ident + ' is not an entry of the English');
        } else if (value === null) {
          /* named and left empty: not translated yet */
        } else if (isPlainObject(from)) {
          if (!isPlainObject(value)) {
            problems.push(ident + ' is a table in English and a sentence here');
            return;
          }
          Object.keys(value).sort().forEach(function (row) {
            if (!own(from, row)) {
              problems.push(ident + '[' + row + '] is not a row of the English table');
            } else if (value[row] === null) {
              /* not translated yet */
            } else if (typeof value[row] !== 'string' || value[row].indexOf('{') >= 0 ||
                value[row].indexOf('}') >= 0) {
              problems.push(ident + '[' + row + '] is not plain text');
            } else if (!textTrimmed(value[row])) {
              problems.push(ident + '[' + row + '] is blank');
            }
          });
        } else if (typeof value !== 'string') {
          problems.push(ident + ' is a sentence in English and not one here');
        } else if (!textTrimmed(value)) {
          problems.push(ident + ' is blank');
        } else {
          var mine = textPlaceholders(value), theirs = textPlaceholders(from);
          if (mine === null) {
            problems.push(ident + ' has a lone brace');
          } else if (theirs !== null && !sameValues(mine, theirs)) {
            problems.push(ident + ' does not take the values the English takes (' +
              (Object.keys(theirs).sort().join(', ') || 'none') +
              '), each written as the English writes it');
          }
        }
      });
    });
    return problems;
  }

  /** @param {Record<string, Rec>} all
   * @param {string} code
   * @returns {Rec} */
  function languageFacts(all, code) {
    /** @type {Rec} */
    var language = { code: code };
    LANGUAGE_FACTS.forEach(function (fact) {
      language[fact] = textTrimmed(all[code].language[fact]);
    });
    return language;
  }

  /** The translations that can be offered, as {code, name, translated_by,
   * checked_by}, by name: those with no problem (text.py languages).
   * @param {Record<string, Rec>} [held]
   * @param {Record<string, Rec>} [english]
   * @returns {Rec[]} */
  function textLanguages(held, english) {
    var all = held || translations();
    /** @type {Rec[]} */
    var offered = [];
    Object.keys(all).sort().forEach(function (code) {
      if (translationProblems(code, all, english).length) return;
      offered.push(languageFacts(all, code));
    });
    return offered.sort(function (a, b) {
      return a.name < b.name ? -1 : (a.name > b.name ? 1
        : (a.code < b.code ? -1 : (a.code > b.code ? 1 : 0)));
    });
  }

  /** The catalogue in one language, with English where it has no words
   * (text.py Speaker). speaker('') is English. A language that cannot be
   * offered is refused with its reasons. fellBack holds what it had to say
   * in English, each once, in the order it was first asked for: a sentence
   * or a whole table by its name, a single row asked for with row() as
   * name[row]. Translated text is tidied as typed text is (textTidy).
   * @param {string} [code]
   * @param {Record<string, Rec>} [held]
   * @param {Record<string, Rec>} [english]
   * @returns {Speaker} */
  function speaker(code, held, english) {
    var lang = code || '';
    var source = english || (GWT.data || {}).text || {};
    /** @type {Record<string, Rec>} */
    var text = {};
    /** @type {Rec} */
    var language = {};
    /** @type {string[]} */
    var fellBack = [];
    if (lang) {
      var all = held || translations();
      var problems = translationProblems(lang, all, source);
      if (problems.length) {
        throw new Error('text: the translation ' + pyRepr(lang) + ' cannot be used: ' +
          problems.join('; '));
      }
      text = all[lang].text || {};
      language = languageFacts(all, lang);
    }
    /** @param {string} id */
    function sourceOf(id) {
      var dot = id.indexOf('.');
      var namespace = id.slice(0, dot), key = id.slice(dot + 1);
      if (dot < 0 || !own(source, namespace) || !own(source[namespace], key)) {
        throw new Error('text: no entry ' + pyRepr(id) + ' in data/text');
      }
      var file = (own(text, namespace) && text[namespace]) || {};
      return { from: source[namespace][key], mine: own(file, key) ? file[key] : null };
    }
    /** @param {string} id */
    function missed(id) {
      if (lang && fellBack.indexOf(id) < 0) fellBack.push(id);
    }
    /** @param {string} id */
    function tableOf(id) {
      var at = sourceOf(id);
      if (!isPlainObject(at.from)) {
        throw new TypeError('text: ' + pyRepr(id) + ' is a sentence; read it with phrase');
      }
      return { from: at.from, mine: at.mine || {} };
    }
    return {
      code: lang, language: language, fellBack: fellBack,
      phrase: function (id, values) {
        var at = sourceOf(id);
        if (typeof at.from !== 'string') {
          throw new TypeError('text: ' + pyRepr(id) + ' is a table; read it with phraseTable');
        }
        if (at.mine === null) {
          missed(id);
          return renderText(at.from, values);
        }
        return renderText(textTidy(at.mine), values);
      },
      /* the whole table, for one every row of which is printed; where one
       * row is chosen, row() keeps a truer count of what fell back */
      phraseTable: function (id) {
        var at = tableOf(id);
        /** @type {Record<string, *>} */
        var table = {};
        var short = false;
        Object.keys(at.from).forEach(function (row) {
          if (own(at.mine, row) && at.mine[row] !== null) table[row] = textTidy(at.mine[row]);
          else { table[row] = at.from[row]; short = true; }
        });
        if (short) missed(id);
        return table;
      },
      row: function (id, row) {
        var at = tableOf(id);
        if (!own(at.from, row)) {
          throw new Error('text: no row ' + pyRepr(row) + ' in ' + pyRepr(id));
        }
        if (!own(at.mine, row) || at.mine[row] === null) {
          missed(id + '[' + row + ']');
          return at.from[row];
        }
        return textTidy(at.mine[row]);
      },
    };
  }

  Object.assign(C, {
    translations: translations, translationProblems: translationProblems,
    textLanguages: textLanguages, speaker: speaker,
  });
