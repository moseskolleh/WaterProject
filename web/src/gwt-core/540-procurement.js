


  /* ===================================================================
   * Procurement - a port of groundwater/procurement.py
   *
   * A bill of quantities is an estimate until somebody signs it. The three
   * ways a drilling contract loses money afterwards are all handled the
   * same way here: measured is not the same as authorised and only the
   * lower one is paid; a certificate subtracts what earlier ones already
   * paid; and retention is withheld and capped rather than forgotten.
   * Nothing is netted away silently - a problem is reported on the face of
   * the certificate.
   * =================================================================== */

  /**
   * @param {Rec} contract
   * @returns {number}
   */
  function contractSum(contract) {
    return (contract.lines || []).reduce(function (total, line) {
      return total + line.quantity * line.rate_usd;
    }, 0);
  }

  /**
   * @param {Rec} contract
   * @returns {number}
   */
  function contractAdvance(contract) {
    return contractSum(contract) * (contract.advance_percent || 0) / 100;
  }

  /* Freeze an estimate into a contract. The estimate keeps moving as the
   * design changes; a contract does not, so this takes the copy that gets
   * signed rather than a reference to the live one. */
  var RATE_BASES = ['price', 'cost', 'price_with_vat'];

  /** basis says what the frozen rates include: the estimate's line rates are
   * the contractor's direct costs, and the figure the same estimate recommends
   * as the contract price is cost plus overheads plus margin, so 'price' (the
   * default) uplifts every rate by that factor. Freezing at the bare cost
   * rates - kept as 'cost' - paid the contractor a third below the price the
   * toolkit had just recommended.
   * @param {Rec} estimate what estimateBoreholeCost returns
   * @param {string} ref
   * @param {Rec} [terms]
   * @param {string} [basis] 'price', 'cost' or 'price_with_vat'
   */
  function contractFromEstimate(estimate, ref, terms, basis) {
    var kind = basis || 'price';
    if (RATE_BASES.indexOf(kind) < 0) {
      throw new Error('basis must be one of ' + RATE_BASES.join(', ') + ', not ' + kind);
    }
    var uplift = 1.0;
    if (kind === 'price' || kind === 'price_with_vat') {
      uplift *= (1.0 + Number(estimate.overheads_percent || 0) / 100.0) *
        (1.0 + Number(estimate.margin_percent || 0) / 100.0);
    }
    if (kind === 'price_with_vat') uplift *= 1.0 + Number(estimate.vat_percent || 0) / 100.0;
    return Object.assign({
      ref: ref, contractor: '', client: '', date: '',
      retention_percent: 10, retention_cap_percent: 5, advance_percent: 0
    }, terms || {}, {
      rate_basis: kind, rate_uplift: uplift,
      lines: (estimate.items || []).map(function (item) {
        return {
          code: item.code, item: item.item, unit: item.unit,
          quantity: Number(item.quantity), rate_usd: Number(item.unit_cost_usd) * uplift,
          stage: item.stage || '', category: item.category || ''
        };
      })
    });
  }

  function valuationFigures(line) {
    /* a variation that omits more than the contract carries authorises
     * nothing, not a negative quantity (which paid phantom overmeasure) */
    var authorised = Math.max(line.contract_quantity + line.variation_quantity, 0);
    var payable = Math.max(Math.min(line.measured_quantity, authorised), 0);
    var over = Math.max(line.measured_quantity - authorised, 0);
    /* the contract amount is valued at the signed rate, so a rate-only
     * variation shows as a variation instead of vanishing from the sum */
    var contractRate = (line.contract_rate_usd === null || line.contract_rate_usd === undefined)
      ? line.rate_usd : line.contract_rate_usd;
    return Object.assign({}, line, {
      authorised_quantity: authorised,
      payable_quantity: payable,
      overmeasure_quantity: over,
      contract_amount_usd: line.contract_quantity * contractRate,
      authorised_amount_usd: authorised * line.rate_usd,
      payable_amount_usd: payable * line.rate_usd,
      overmeasure_amount_usd: over * line.rate_usd,
      percent_complete: authorised ? payable / authorised * 100 : null
    });
  }

  /** Returns {lines, problems}. The problems are written for the person who
   * has to fix them, and are never fatal: a certificate with a problem on it
   * is still worth issuing, as long as the problem is printed on its face.
   * @param {Rec} contract
   * @param {Rec[]|null} measurements
   * @param {Rec[]|null} [variations]
   */
  function valueWork(contract, measurements, variations) {
    var problems = [], varied = {}, order = [];
    (variations || []).forEach(function (v) {
      if (!own(varied, v.code)) {
        varied[v.code] = { delta: 0, rate: null, refs: [], unsignedRefs: [],
          item: '', unit: '' };
        order.push(v.code);
      }
      var entry = varied[v.code];
      entry.item = entry.item || v.item || '';
      entry.unit = entry.unit || v.unit || '';
      /* An unsigned variation is not valued at all. Counting its quantity and
       * then printing a warning beside the total pays for work nobody
       * instructed: the warning is read once, the certificate is banked. */
      if (!v.authorised_by) {
        entry.unsignedRefs.push(v.ref);
        problems.push('Variation ' + v.ref + ' on ' + v.code + ' names nobody ' +
          'who authorised it. An unsigned variation is a request, not an ' +
          'instruction, so its quantity is left out of this valuation until ' +
          'somebody signs it.');
        return;
      }
      entry.delta += Number(v.quantity_delta || 0);
      entry.refs.push(v.ref);
      if (v.rate_usd !== null && v.rate_usd !== undefined) {
        entry.rate = Number(v.rate_usd);
      }
    });

    var measured = {}, measuredOrder = [];
    (measurements || []).forEach(function (m) {
      if (Number(m.quantity) < 0) {
        problems.push(m.code + ' is measured as a negative quantity (' +
          formatG(Number(m.quantity)) + '); it is treated as nothing measured.');
        return;
      }
      /* cumulative-to-date, so the latest figure wins rather than a running
       * total being accumulated twice */
      if (!own(measured, m.code)) measuredOrder.push(m.code);
      measured[m.code] = Number(m.quantity);
    });

    var lines = [], seen = {}, duplicates = [];
    (contract.lines || []).forEach(function (line) {
      if (own(seen, line.code)) {
        /* two contract lines under one code would each be paid the one
         * measurement; the first is valued and the rest are named */
        duplicates.push(line.code);
        return;
      }
      var change = own(varied, line.code) ? varied[line.code] : {};
      seen[line.code] = true;
      var delta = change.delta || 0;
      if (delta < 0 && -delta > line.quantity) {
        problems.push('Variation ' + (change.refs || []).join(', ') + ' omits ' +
          formatG(-delta) + ' ' + line.unit + ' of ' + line.code + ' but the ' +
          'contract only carries ' + formatG(line.quantity) + '; the line is ' +
          'treated as fully omitted and nothing on it is payable.');
      }
      lines.push(valuationFigures({
        code: line.code, item: line.item, unit: line.unit,
        rate_usd: (change.rate === null || change.rate === undefined)
          ? line.rate_usd : change.rate,
        contract_quantity: line.quantity,
        variation_quantity: delta,
        measured_quantity: own(measured, line.code) ? measured[line.code] : 0,
        in_contract: true,
        variation_refs: (change.refs || []).slice(),
        contract_rate_usd: line.rate_usd
      }));
    });
    if (duplicates.length) {
      var named = duplicates.filter(function (c, i) { return duplicates.indexOf(c) === i; });
      problems.push('The contract carries more than one line coded ' + named.join(', ') +
        '; only the first line under each code is valued, so recode the others ' +
        'before the next certificate.');
    }

    order.concat(measuredOrder.filter(function (c) { return !own(varied, c); }))
      .forEach(function (code) {
        if (own(seen, code)) return;
        seen[code] = true;
        var change = own(varied, code) ? varied[code] : null;
        if (!change) {
          problems.push(code + ' has been measured but is neither in the ' +
            'contract nor in any variation, so there is no rate to pay it at ' +
            'and nothing authorising it. It is valued at zero.');
          lines.push(valuationFigures({
            code: code, item: '(not in the contract)', unit: '', rate_usd: 0,
            contract_quantity: 0, variation_quantity: 0,
            measured_quantity: own(measured, code) ? measured[code] : 0,
            in_contract: false, variation_refs: []
          }));
          return;
        }
        if (!change.refs.length) {
          problems.push('Variation ' + change.unsignedRefs.join(', ') + ' adds ' +
            code + ', which the contract does not carry, and nobody has signed ' +
            'it. Nothing is authorised against this line, so nothing on it is ' +
            'payable.');
        } else if (change.rate === null || change.rate === undefined) {
          problems.push('Variation ' + change.refs.join(', ') + ' adds ' + code +
            ', which the contract does not price, without giving a rate. It is ' +
            'valued at zero until one is agreed.');
        }
        lines.push(valuationFigures({
          code: code, item: change.item || '(added by variation)',
          unit: change.unit || '', rate_usd: change.rate || 0,
          contract_quantity: 0, variation_quantity: change.delta || 0,
          measured_quantity: own(measured, code) ? measured[code] : 0,
          in_contract: false, variation_refs: change.refs.slice()
        }));
      });

    lines.forEach(function (line) {
      if (line.overmeasure_quantity > 0) {
        problems.push(line.code + ' is measured at ' +
          formatG(line.measured_quantity) + ' ' + line.unit + ' against ' +
          formatG(line.authorised_quantity) + ' authorised. The extra ' +
          formatG(line.overmeasure_quantity) + ' is not payable until a ' +
          'variation authorises it - the work may well be justified, but that ' +
          'is a decision somebody signs, not a measurement.');
      }
    });
    return { lines: lines, problems: problems };
  }

  /** options: {number, date, variations, previouslyCertifiedUsd, preparedBy}
   * @param {Rec} contract
   * @param {Rec[]|null} measurements
   * @param {Rec} [options] number, date, variations, previouslyCertifiedUsd, preparedBy
   */
  function certify(contract, measurements, options) {
    var opts = options || {};
    var valued = valueWork(contract, measurements, opts.variations || []);
    var problems = valued.problems.slice();
    var previous = Number(opts.previouslyCertifiedUsd || 0);
    var number = Number(opts.number || 1);
    if (previous < 0) {
      problems.push('Previously certified is negative, which cannot be right; ' +
        'it is treated as nothing certified so far.');
      previous = 0;
    }
    if (number > 1 && previous === 0) {
      problems.push('This is certificate ' + number + ' but nothing is ' +
        'recorded as previously certified. If earlier certificates were paid, ' +
        'the contractor will be paid for that work twice.');
    }

    var gross = valued.lines.reduce(function (t, l) {
      return t + l.payable_amount_usd;
    }, 0);
    var sum = contractSum(contract);
    var variationValue = valued.lines.reduce(function (t, l) {
      return t + (l.authorised_amount_usd - l.contract_amount_usd);
    }, 0);
    var revised = sum + variationValue;
    var held = gross * (contract.retention_percent || 0) / 100;
    var cap = revised * (contract.retention_cap_percent || 0) / 100;
    var retention = Math.min(held, cap);
    var advance = contractAdvance(contract);
    var recovered = (!advance || !revised) ? 0
      : Math.min(advance * gross / revised, advance);
    var net = gross - retention - recovered;
    var due = Math.max(net - previous, 0);
    var overpaid = Math.max(previous - net, 0);
    var percent = revised ? gross / revised * 100 : null;

    var summary = 'Certificate ' + number + ': ' + money0(due) +
      ' due on work valued at ' + money0(gross);
    if (percent !== null) {
      summary += ' (' + pyFixed(percent, 0) + '% of the revised sum)';
    }
    if (overpaid) {
      summary += '. Previous certificates exceed the value of the work by ' +
        money0(overpaid) + ', so nothing is due';
    }

    return {
      number: number, date: opts.date || '', contract_ref: contract.ref,
      lines: valued.lines, problems: problems,
      prepared_by: opts.preparedBy || '',
      contract_sum_usd: sum, variation_usd: variationValue,
      revised_sum_usd: revised, gross_usd: gross,
      percent_complete: percent, retention_usd: retention,
      advance_recovered_usd: recovered, net_certified_usd: net,
      previously_certified_usd: previous, due_now_usd: due,
      overpaid_usd: overpaid,
      overmeasure_usd: valued.lines.reduce(function (t, l) {
        return t + l.overmeasure_amount_usd;
      }, 0),
      summary: summary + '.'
    };
  }

  /** Python's "${:,.0f}". Rounded through pyRound first: a retention of
   * exactly 344.5 is 344 in Python and 345 through toLocaleString, and a
   * certificate that differs from the toolkit's by a dollar is a
   * certificate somebody has to reconcile by hand.
   * @param {number|string} value
   * @returns {string}
   */
  function money0(value) {
    return '$' + thousandsFixed(pyRound(Number(value), 0), 0);
  }

  /**
   * @param {Rec} contract
   * @param {Rec} certificate what certify returns
   * @returns {string[][]}
   */
  function contractSummaryRows(contract, certificate) {
    var rows = [['Contract', contract.ref]];
    if (contract.contractor) rows.push(['Contractor', contract.contractor]);
    if (contract.client) rows.push(['Client', contract.client]);
    rows.push(['Contract sum', money0(certificate.contract_sum_usd)]);
    rows.push(['Variations', (certificate.variation_usd < 0 ? '-' : '+') +
      money0(Math.abs(certificate.variation_usd))]);
    rows.push(['Revised sum', money0(certificate.revised_sum_usd)]);
    rows.push(['Work valued to date', money0(certificate.gross_usd)]);
    if (certificate.percent_complete !== null) {
      rows.push(['Progress', pyFixed(certificate.percent_complete, 0) + '%']);
    }
    rows.push(['Less retention (' + formatG(contract.retention_percent) + '%)',
      '-' + money0(certificate.retention_usd)]);
    if (contract.advance_percent) {
      rows.push(['Less advance recovery (' + formatG(contract.advance_percent) +
        '% advance)', '-' + money0(certificate.advance_recovered_usd)]);
    }
    rows.push(['Net certified to date', money0(certificate.net_certified_usd)]);
    rows.push(['Less previously certified',
      '-' + money0(certificate.previously_certified_usd)]);
    rows.push(['Due on this certificate', money0(certificate.due_now_usd)]);
    return rows;
  }

  Object.assign(C, {
    contractSum: contractSum, contractAdvance: contractAdvance,
    contractFromEstimate: contractFromEstimate, valueWork: valueWork,
    certify: certify, contractSummaryRows: contractSummaryRows,
    money0: money0
  });
